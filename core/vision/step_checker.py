import base64
import time

import cv2

from core.llm.client import generate
from core.vision.image_handler import transcribe
from core.vision.preprocess import preprocess
from core.vision.segment import crops, segment

# Groq returns 429 (rate limit) and 503 (model over capacity) under load, and
# its own error message says to back off exponentially. Each check_working call
# fires many model calls, so one transient hiccup shouldn't sink the whole run.
_TRANSIENT = ("429", "503", "over capacity", "rate limit", "try again")


def _with_retry(fn, *, tries=3):
    """Run a model call, retrying transient Groq errors with backoff."""
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:
            transient = any(t in str(e).lower() for t in _TRANSIENT)
            if not transient or attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)   # 1s, then 2s

CHECK_PROMPT = (
    "A student wrote two consecutive lines of mathematical working:\n\n"
    "Line {i}: {prev}\n"
    "Line {j}: {curr}\n\n"
    "Does line {j} follow correctly from line {i}? "
    "Reply with YES if it does. Reply with NO and one sentence explaining "
    "the error if it does not. Start your answer with YES or NO."
)

MIN_STEP_CHARS = 2


def _low_confidence(text: str) -> bool:
    """A transcription we don't trust enough to judge against."""
    t = (text or "").strip()
    return (not t) or t == "[unreadable]" or len(t) < MIN_STEP_CHARS


def _read_box(binary, box, i, *, pad, provider, model, host, api_key, vision_model) -> str:
    """Crop one line at the given padding and transcribe it."""
    crop = crops(binary, [box], pad=pad)[0]
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
