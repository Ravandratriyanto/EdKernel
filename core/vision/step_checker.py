import base64
import re
import time

import cv2

from core.llm.client import generate
from core.vision.image_handler import transcribe
from core.vision.preprocess import preprocess
from core.vision.segment import crops, segment

# Groq returns 429 (rate limit) and 503 (model over capacity) under load, and
# its own error message says to back off exponentially. Each check_working call
# fires many model calls, so one transient hiccup shouldn't sink the whole run.
# "connection error" is in here because that is the *only* text an
# APIConnectionError carries — a throttled run surfaces as a bare connection
# drop, and the old list missed it, discarding whole eval cases.
_TRANSIENT = ("429", "503", "502", "504", "over capacity", "rate limit",
              "try again", "connection error", "timeout", "timed out")

# Groq's 429 body names the exact wait: "Please try again in 15.557142857s".
# On the free tier the input-token-per-minute window is ~7000 and one page
# photo costs ~2000, so the real wait is tens of seconds — far longer than an
# exponential backoff starting at 1s would ever reach. Honour the number.
_RETRY_AFTER_RE = re.compile(r"try again in ([\d.]+)s", re.I)


def _retry_delay(err: Exception, attempt: int) -> float:
    """How long to wait before the next attempt, capped so a run can't stall."""
    m = _RETRY_AFTER_RE.search(str(err))
    if m:
        try:
            return min(float(m.group(1)) + 1.0, 65.0)
        except ValueError:
            pass
    # 503 "over capacity" carries no wait hint and does not clear in a second.
    # 3s, 6s, 12s, 24s rides out a short incident; 1/2/4 never did.
    return 3 * (2 ** attempt)


def _with_retry(fn, *, tries=4):
    """Run a model call, retrying transient Groq errors with backoff."""
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:
            transient = any(t in str(e).lower() for t in _TRANSIENT)
            if not transient or attempt == tries - 1:
                raise
            time.sleep(_retry_delay(e, attempt))

CHECK_PROMPT = (
    "You are a Cambridge examiner checking a student's working for method marks. "
    "A method mark (M) is earned when a line follows from the line above by a "
    "valid step, and is lost at the first line that does not.\n\n"
    "Line {i}: {prev}\n"
    "Line {j}: {curr}\n\n"
    "Does line {j} follow correctly from line {i}? "
    "If line {j} simply restates line {i} unchanged, the student has copied "
    "the line out again before working on it. That is valid, not an error — "
    "reply YES. "
    "Reply YES if it follows. "
    "If it does not, reply NO followed by one sentence in an examiner's voice: "
    "name the method mark lost at this line and the correct step the student "
    "should have taken. Start your answer with YES or NO."
)

MIN_STEP_CHARS = 2


_SAME_STRIP = re.compile(r"[\s$,.;{}]|\\quad|\\,|\\!|\\left|\\right|\\\\")
_QNUM = re.compile(r"^\d{1,2}\)")


def _flatten(s: str) -> str:
    """Reduce a transcribed line to comparable form.

    The model does not render the same line identically twice: "$x=6$" vs
    "$x = 6$", "x^2" vs "x^{2}", and only the FIRST line of a problem picks up
    the question number ("9)."). All three made a genuine repeat look like a
    new step, so strip all three before comparing.
    """
    s = _SAME_STRIP.sub("", (s or "").lower())
    return _QNUM.sub("", s)


def _same_line(a: str, b: str) -> bool:
    """True when two transcribed lines say the same thing."""
    na, nb = _flatten(a), _flatten(b)
    return bool(na) and na == nb


def _low_confidence(text: str) -> bool:
    """A transcription we don't trust enough to judge against."""
    t = (text or "").strip()
    return (not t) or t == "[unreadable]" or len(t) < MIN_STEP_CHARS


# A segmented line off a phone photo is often only ~25-35px tall. That is far
# below what a vision model can read -- it returned "-20" for "4x = 20" -- and
# no prompt fixes it. Upscale the crop before sending. Cubic on a binarised
# image keeps the strokes smooth rather than blocky.
MIN_READ_HEIGHT = 96
MAX_READ_SCALE = 6.0


def _upscale(crop):
    """Enlarge a line crop to something a vision model can actually read."""
    h, w = crop.shape[:2]
    if h <= 0 or w <= 0 or h >= MIN_READ_HEIGHT:
        return crop
    scale = min(MIN_READ_HEIGHT / float(h), MAX_READ_SCALE)
    return cv2.resize(crop, (int(w * scale), int(h * scale)),
                      interpolation=cv2.INTER_CUBIC)


def _read_box(binary, box, i, *, pad, provider, model, host, api_key, vision_model) -> str:
    """Crop one line at the given padding and transcribe it."""
    crop = _upscale(crops(binary, [box], pad=pad)[0])
    ok, buf = cv2.imencode(".jpg", crop)
    if not ok:
        return "[unreadable]"
    b64 = base64.b64encode(buf.tobytes()).decode()
    text = _with_retry(lambda: transcribe(
        b64, name=f"step{i}.jpg", provider=provider, host=host,
        model=model, api_key=api_key, vision_model=vision_model)).strip()
    return text or "[unreadable]"


def _annotate(binary, boxes, error_index) -> str | None:
    vis = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    for i, (x, y, w, h) in enumerate(boxes):
        is_err = (i == error_index)
        colour = (0, 0, 255) if is_err else (60, 160, 60)   # BGR: red / green
        cv2.rectangle(vis, (x, y), (x + w, y + h), colour, 3 if is_err else 2)
        cv2.putText(vis, str(i + 1), (x + 4, max(16, y + h - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)
    ok, buf = cv2.imencode(".jpg", vis)
    return base64.b64encode(buf.tobytes()).decode() if ok else None


def check_working(path, *, provider, model, host, api_key, vision_model) -> dict:    
    binary = preprocess(path)
    boxes = segment(binary)
    steps = []
    trace = [f"Perceived {len(boxes)} line(s) of working."]

    for i, box in enumerate(boxes):
        text = _read_box(binary, box, i, pad=3, provider=provider, model=model,
                         host=host, api_key=api_key, vision_model=vision_model)
        if _low_confidence(text):
            # Agentic re-capture: low confidence → re-crop this line wider, re-read once.
            trace.append(f"Line {i + 1} unclear — re-cropped wider and re-read.")
            text = _read_box(binary, box, i, pad=14, provider=provider, model=model,
                             host=host, api_key=api_key, vision_model=vision_model)
            if _low_confidence(text):
                trace.append(f"Line {i + 1} still unclear — asking student for a sharper photo.")
        steps.append(text)


    error_index = None
    explanation = None
    for i in range(1, len(steps)):
        if _low_confidence(steps[i]) or _low_confidence(steps[i - 1]):
            continue
        if _same_line(steps[i], steps[i - 1]):
            # Students routinely copy a line out again before working on it.
            # The model called that "no transformation has been performed" and
            # flagged it as THE error, masking the real mistake further down.
            # Decide it here instead of asking: identical lines always follow,
            # and this costs no model call.
            trace.append(f"Line {i + 1} repeats line {i} — skipped, not an error.")
            continue
        prompt = CHECK_PROMPT.format(i=i, j=i + 1,
                                     prev=steps[i - 1], curr=steps[i])
        reply = _with_retry(lambda: generate(prompt, model=model, host=host,
                                             provider=provider, api_key=api_key))
        if reply.strip().upper().startswith("NO"):
            error_index = i
            explanation = reply.strip()[2:].strip()
            trace.append(f"Line {i + 1} does not follow from line {i} — flagged as the error.")
            break
    if error_index is None:
        trace.append("Every step follows — no error found.")

    return {
        "steps": steps,
        "boxes": boxes,
        "image_size": [binary.shape[0], binary.shape[1]],
        "error_index": error_index,
        "explanation": explanation,
        "annotated": _annotate(binary, boxes, error_index),
        "trace": trace,
    }
