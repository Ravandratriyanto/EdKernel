"""Turn a filmed question into one piece of text.

Frames of the same page transcribe to nearly the same words, so near-identical
transcriptions are collapsed here, for free. Only a video that really shows
different things costs an extra model call to stitch together.
"""

import base64
import difflib

from llm.client import generate
from vision.image_handler import transcribe, drop_reasoning
from video.frame_extractor import extract_frames, ExtractError

SAME_ENOUGH = 0.85      # difflib ratio above which two frames read as one page

MERGE_PROMPT = (
    "These are transcriptions of different frames of one video showing a "
    "single exam question. They overlap, and some are partly wrong.\n"
    "Combine them into one complete question. Keep every number, symbol and "
    "equation. Where two frames disagree, choose the reading that makes the "
    "mathematics valid. Do not answer the question. Do not add anything that "
    "is not in the transcriptions.\n"
    "Output only the combined question.\n\n"
)


def _dedupe(texts: list[str]) -> list[str]:
    """Collapse transcriptions that say the same thing, keeping the fullest."""
    kept = []
    for t in texts:
        for i, k in enumerate(kept):
            # SequenceMatcher(None, a, b).ratio() scores 0-1 on how alike two
            # strings are. The None is the "junk" argument — nothing to ignore.
            if difflib.SequenceMatcher(None, t, k).ratio() > SAME_ENOUGH:
                # Same page twice. Keep the longer read: a blurred or
                # half-covered frame transcribes short, not wrong.
                if len(t) > len(k):
                    kept[i] = t
                break
        else:
            # for/else: this runs only when the loop ends *without* hitting
            # `break` — i.e. this text matched nothing already kept, so it is
            # a new page.
            kept.append(t)
    return kept


def question_from_video(path: str, model: str = "gemma4",
                        host: str = "http://localhost:11434",
                        provider: str = "ollama", api_key: str = "",
                        vision_model: str = "", on_progress=None) -> str:
    """Return the question in a video as plain text."""
    frames = extract_frames(path)

    texts = []
    for n, jpg in enumerate(frames, 1):
        if on_progress:
            on_progress(n, len(frames))
        b64 = base64.b64encode(jpg).decode()
        try:
            t = transcribe(b64, name=f"frame{n}.jpg", provider=provider,
                           model=model, host=host, api_key=api_key,
                           vision_model=vision_model).strip()
        except Exception:
            continue        # one bad frame must not lose the others
        if t:
            texts.append(t)

    if not texts:
        raise ExtractError(f"Nothing readable in any frame of {path}")

    texts = _dedupe(texts)
    if len(texts) == 1:
        return texts[0]     # static page — the common case, and free

    numbered = "\n\n".join(f"Frame {i}:\n{t}" for i, t in enumerate(texts, 1))
    merged = generate(MERGE_PROMPT + numbered, model=model, host=host,
                      provider=provider, api_key=api_key)
    # generate() hits the text model, which can also reason out loud. Note this
    # drops .usage — LLMText only survives until the first transform.
    return drop_reasoning(merged).strip() or texts[0]
