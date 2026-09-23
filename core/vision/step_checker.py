import base64
import re
import time
import cv2
from core.llm.client import generate
import core.misconceptions
from core.vision.image_handler import transcribe
from core.vision.preprocess import preprocess
from core.vision.segment import crops, segment
_TRANSIENT = ('429', '503', '502', '504', 'over capacity', 'rate limit', 'try again', 'connection error', 'timeout', 'timed out')
_RETRY_AFTER_RE = re.compile('try again in ([\\d.]+)s', re.I)

def _retry_delay(err: Exception, attempt: int) -> float:
    m = _RETRY_AFTER_RE.search(str(err))
    if m:
        try:
            return min(float(m.group(1)) + 1.0, 65.0)
        except ValueError:
            pass
    return 3 * 2 ** attempt

def _with_retry(fn, *, tries=4):
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:
            transient = any((t in str(e).lower() for t in _TRANSIENT))
            if not transient or attempt == tries - 1:
                raise
            time.sleep(_retry_delay(e, attempt))
CHECK_PROMPT = "You are a Cambridge examiner checking a student's working for method marks. A method mark (M) is earned when a line follows from the line above by a valid step, and is lost at the first line that does not.\n\nLine {i}: {prev}\nLine {j}: {curr}\n\nDoes line {j} follow correctly from line {i}? If line {j} simply restates line {i} unchanged, the student has copied the line out again before working on it. That is valid, not an error — reply YES. Do NOT penalise notation or formatting: an omitted '= 0', writing a standalone expression as an equation before factorising, a leading question number (e.g. '4)'), or rearranging the same terms are NOT method errors. Only a genuine mathematical mistake — wrong arithmetic, a bad algebraic step, a sign error — loses a method mark. Reply YES if it follows. If it does NOT, reply NO, then a category in square brackets, then one sentence in an examiner's voice naming the correct step the student should have taken. Choose the category from ONLY these, based on the actual mistake:\n[sign] a + / - sign is wrong (e.g. dividing by a negative and keeping it positive)\n[arithmetic] a pure number calculation is wrong (e.g. 7 + 8 taken as 14)\n[algebra_step] a term was dropped, a step skipped, or the wrong operation used to rearrange\n[other] none of these\nFor example: 'NO [sign] Divide both sides by -3 to obtain x = -4.' Start your answer with YES or NO."
MIN_STEP_CHARS = 2
_SAME_STRIP = re.compile('[\\s$,.;{}]|\\\\quad|\\\\,|\\\\!|\\\\left|\\\\right|\\\\\\\\')
_QNUM = re.compile('^\\d{1,2}\\)')

def _flatten(s: str) -> str:
    s = _SAME_STRIP.sub('', (s or '').lower())
    return _QNUM.sub('', s)

def _same_line(a: str, b: str) -> bool:
    na, nb = (_flatten(a), _flatten(b))
    return bool(na) and na == nb

def _low_confidence(text: str) -> bool:
    t = (text or '').strip()
    return not t or t == '[unreadable]' or len(t) < MIN_STEP_CHARS
MIN_READ_HEIGHT = 96
MAX_READ_SCALE = 6.0

def _upscale(crop):
    h, w = crop.shape[:2]
    if h <= 0 or w <= 0 or h >= MIN_READ_HEIGHT:
        return crop
    scale = min(MIN_READ_HEIGHT / float(h), MAX_READ_SCALE)
    return cv2.resize(crop, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

def _read_box(binary, box, i, *, pad, provider, model, host, api_key, vision_model) -> str:
    crop = _upscale(crops(binary, [box], pad=pad)[0])
    ok, buf = cv2.imencode('.jpg', crop)
    if not ok:
        return '[unreadable]'
    b64 = base64.b64encode(buf.tobytes()).decode()
    text = _with_retry(lambda: transcribe(b64, name=f'step{i}.jpg', provider=provider, host=host, model=model, api_key=api_key, vision_model=vision_model)).strip()
    return text or '[unreadable]'

def _annotate(binary, boxes, error_index) -> str | None:
    vis = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    for i, (x, y, w, h) in enumerate(boxes):
        is_err = i == error_index
        colour = (0, 0, 255) if is_err else (60, 160, 60)
        cv2.rectangle(vis, (x, y), (x + w, y + h), colour, 3 if is_err else 2)
        cv2.putText(vis, str(i + 1), (x + 4, max(16, y + h - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)
    ok, buf = cv2.imencode('.jpg', vis)
    return base64.b64encode(buf.tobytes()).decode() if ok else None

def check_working(path, *, provider, model, host, api_key, vision_model) -> dict:
    binary = preprocess(path)
    boxes = segment(binary)
    steps = []
    trace = [f'Perceived {len(boxes)} line(s) of working.']
    for i, box in enumerate(boxes):
        text = _read_box(binary, box, i, pad=3, provider=provider, model=model, host=host, api_key=api_key, vision_model=vision_model)
        if _low_confidence(text):
            trace.append(f'Line {i + 1} unclear — re-cropped wider and re-read.')
            text = _read_box(binary, box, i, pad=14, provider=provider, model=model, host=host, api_key=api_key, vision_model=vision_model)
            if _low_confidence(text):
                trace.append(f'Line {i + 1} still unclear — asking student for a sharper photo.')
        steps.append(text)
    error_index = None
    explanation = None
    category = None
    for i in range(1, len(steps)):
        if _low_confidence(steps[i]) or _low_confidence(steps[i - 1]):
            continue
        if _same_line(steps[i], steps[i - 1]):
            trace.append(f'Line {i + 1} repeats line {i} — skipped, not an error.')
            continue
        prompt = CHECK_PROMPT.format(i=i, j=i + 1, prev=steps[i - 1], curr=steps[i])
        reply = _with_retry(lambda: generate(prompt, model=model, host=host, provider=provider, api_key=api_key))
        if reply.strip().upper().startswith('NO'):
            error_index = i
            rest = reply.strip()[2:].strip()
            tag = re.match('\\[([a-z_]+)\\]', rest)
            category = core.misconceptions.normalise(tag.group(1) if tag else '')
            explanation = rest[tag.end():].strip() if tag else rest
            trace.append(f'Line {i + 1} does not follow from line {i} — flagged as the error ({category}).')
            break
    if error_index is None:
        trace.append('Every step follows — no error found.')
    return {'steps': steps, 'boxes': boxes, 'image_size': [binary.shape[0], binary.shape[1]], 'error_index': error_index, 'explanation': explanation, 'category': category, 'annotated': _annotate(binary, boxes, error_index), 'trace': trace}