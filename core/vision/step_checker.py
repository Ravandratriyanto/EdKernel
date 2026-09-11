import base64

import cv2

from core.llm.client import generate
from core.vision.image_handler import transcribe
from core.vision.preprocess import preprocess
from core.vision.segment import crops, segment

CHECK_PROMPT = (
    "A student wrote two consecutive lines of mathematical working:\n\n"
    "Line {i}: {prev}\n"
    "Line {j}: {curr}\n\n"
    "Does line {j} follow correctly from line {i}? "
    "Reply with YES if it does. Reply with NO and one sentence explaining "
    "the error if it does not. Start your answer with YES or NO."
)


def _annotate(binary, boxes, error_index) -> str | None:
    """Draw the segmented lines on the cleaned page and return a base64 JPEG.

    Boxes are in the preprocessed image's coordinate space, so we draw on that
    image — the rectangles line up by construction, unlike scaling them back
    onto the raw photo after a perspective warp or deskew. The error line is red
    and thicker; every other line is green.
    """
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
    """Transcribe each line of handwritten working and find the first wrong step.

    Returns a dict with:
      steps       — transcribed text per line, in reading order
      boxes       — (x, y, w, h) bounding boxes parallel to steps
      error_index — 0-based index of the first wrong step, or None
      explanation — why that step is wrong, or None
      annotated   — base64 JPEG of the page with lines boxed (error in red)
    """
    binary = preprocess(path)
    boxes = segment(binary)
    steps = []

    for i, crop in enumerate(crops(binary, boxes)):
        ok, buf = cv2.imencode(".jpg", crop)
        if not ok:
            steps.append("[unreadable]")
            continue
        b64 = base64.b64encode(buf.tobytes()).decode()
        text = transcribe(b64, name=f"step{i}.jpg",
                          provider=provider, model=model,
                          host=host, api_key=api_key,
                          vision_model=vision_model).strip()
        steps.append(text or "[unreadable]")

    error_index = None
    explanation = None
    for i in range(1, len(steps)):
        if steps[i] == "[unreadable]" or steps[i - 1] == "[unreadable]":
            continue
        prompt = CHECK_PROMPT.format(i=i, j=i + 1,
                                     prev=steps[i - 1], curr=steps[i])
        reply = generate(prompt, model=model, host=host,
                         provider=provider, api_key=api_key)
        if reply.strip().upper().startswith("NO"):
            error_index = i
            explanation = reply.strip()[2:].strip()
            break

    return {
        "steps": steps,
        "boxes": boxes,
        "image_size": [binary.shape[0], binary.shape[1]],
        "error_index": error_index,
        "explanation": explanation,
        "annotated": _annotate(binary, boxes, error_index),
    }
