"""Turn a photographed question into text.

Groq's text models drop image data, so images are transcribed to plain text
first and fed into the normal learn/check flow — which every provider accepts.
"""


GROQ_VISION_MODEL = "qwen/qwen3.8-27b"  # qwen3.6-27b was decommissioned by Groq

DETECT_PROMPT = (
    "Look at this image. If it contains a printed or handwritten mathematical "
    "question, problem, or exercise, transcribe it as plain text — "
    "use LaTeX notation for any maths (e.g. \\(x^2\\), \\(\\frac{a}{b}\\)). "
    "Include every part of the question: the stem, all sub-parts (a), (b)…, "
    "and describe any diagram in one sentence. "
    "If the image does NOT contain a clear question or problem "
    "(e.g. it is handwritten calculation steps, a blank page, or an unrelated photo), "
    "respond with exactly: NO_QUESTION\n"
    "Output only the transcription or NO_QUESTION. No preamble, no explanation."
)

TRANSCRIBE_PROMPT = (
    "Transcribe the handwritten mathematics in this image as a single line of "
    "plain text, using LaTeX for any mathematics. "
    "This is a student's working and it may contain mistakes. "
    "Copy it verbatim: do NOT correct errors, do NOT solve, simplify, or 'fix' "
    "anything. If a step is wrong, transcribe the wrong version exactly as it "
    "is written. "
    "Write the expression exactly once — do NOT repeat it, and do NOT break it "
    "into separate fragments or pieces. "
    "Output only the transcription — no preamble, no explanation, no answer."
)

_MIME = {
    "png":  "image/png",
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif":  "image/gif",
}

def _mime_for(name: str) -> str:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    return _MIME.get(ext, "image/png")

def drop_reasoning(text: str) -> str:
    """Strip a reasoning model's <think> block from a transcription.

    The default Groq vision model reasons out loud, and the visible answer is
    whatever follows the final </think>. Without this the tutor receives ~3000
    characters of the model talking to itself as the student's question.

    Splitting on the closing tag rather than matching a <think>...</think> pair
    also covers models that emit the closing tag with no opening one.

    An *unclosed* block returns empty. Seen live on a video frame: the model
    opened <think>, never closed it, and 6,146 characters of it talking to
    itself came back as the transcription. There is no answer inside that, so
    the honest result is nothing — callers already treat empty as unreadable
    and skip the frame, which is far better than teaching the monologue.
    """
    if "</think>" in text:
        return text.rsplit("</think>", 1)[1].strip()
    if "<think>" in text:
        return ""
    return text.strip()

def detect_question(b64: str, name: str = "image.png", provider: str = "ollama",
                    model: str = "gemma4", host: str = "http://localhost:11434",
                    api_key: str = "", vision_model: str = "") -> dict:
    """Return {"found": bool, "question": str} from an image.

    Returns found=False for handwritten working, blank pages, or anything that
    is not a clear question or problem statement.
    """
    if provider == "groq":
        raw = _groq_vision(DETECT_PROMPT, b64, name, vision_model or GROQ_VISION_MODEL, api_key)
    else:
        from ollama import Client as OllamaClient
        client = OllamaClient(host=host)
        messages = [{"role": "user", "content": DETECT_PROMPT, "images": [b64]}]
        raw = drop_reasoning(client.chat(model=model, messages=messages).message.content)
    raw = (raw or "").strip()
    if not raw or raw.upper().startswith("NO_QUESTION") or len(raw) < 8:
        return {"found": False, "question": ""}
    return {"found": True, "question": raw}


def transcribe(b64: str, name: str = "image.png", provider: str = "ollama",
               model: str = "gemma4", host: str = "http://localhost:11434",
               api_key: str = "", vision_model: str = "") -> str:
    """Return a text transcription of the question in a base64-encoded image."""
    if provider == "groq":
        return _groq_vision(TRANSCRIBE_PROMPT, b64, name, vision_model or GROQ_VISION_MODEL, api_key)

    from ollama import Client as OllamaClient
    client = OllamaClient(host=host)
    messages = [{"role": "user", "content": TRANSCRIBE_PROMPT, "images": [b64]}]
    return drop_reasoning(client.chat(model=model, messages=messages).message.content)

def _groq_vision(prompt: str, b64: str, name: str, vision_model: str, api_key: str) -> str:
    from groq import Groq
    # Without an explicit timeout the SDK waits 600s and retries twice on its
    # own, so one stuck call can hang a run for half an hour. Fail fast and let
    # _with_retry in step_checker.py decide whether to try again.
    client = Groq(api_key=api_key, timeout=60.0, max_retries=0)
    response = client.chat.completions.create(
        model=vision_model,
        # The only vision models on Groq are qwen *reasoning* models. Left on,
        # they burn the whole token budget thinking and return nothing on a
        # dense photo. "none" disables reasoning so the tokens go to the answer.
        reasoning_effort="none",
        # Groq free tier caps output at 1000 tokens/min; a line of working needs
        # far less. Also keeps a single call under the per-minute limit.
        max_tokens=512,
        # Pin temperature so transcription is reproducible — otherwise the same
        # image reads cleanly one run and fragmented the next, and a noisy read
        # poisons the downstream step check.
        temperature=0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:{_mime_for(name)};base64,{b64}"}},
            ],
        }],
    )
    return drop_reasoning(response.choices[0].message.content)
