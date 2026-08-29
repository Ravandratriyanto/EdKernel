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


def check_working(path, *, provider, model, host, api_key, vision_model) -> dict:
    """Transcribe each line of handwritten working and find the first wrong step.

    Returns a dict with:
      steps       — transcribed text per line, in reading order
      boxes       — (x, y, w, h) bounding boxes parallel to steps
      error_index — 0-based index of the first wrong step, or None
      explanation — why that step is wrong, or None
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

    for i in range(1, len(steps)):
        if steps[i] == "[unreadable]" or steps[i - 1] == "[unreadable]":
            continue
        prompt = CHECK_PROMPT.format(i=i, j=i + 1,
                                     prev=steps[i - 1], curr=steps[i])
        reply = generate(prompt, model=model, host=host,
                         provider=provider, api_key=api_key)
        if reply.strip().upper().startswith("NO"):
            return {
                "steps": steps,
                "boxes": boxes,
                "error_index": i,
                "explanation": reply.strip()[2:].strip(),
            }

    return {"steps": steps, "boxes": boxes, "error_index": None, "explanation": None}
