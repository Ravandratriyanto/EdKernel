"""Turn a photographed question into text.

Groq's text models drop image data, so images are transcribed to plain text
first and fed into the normal learn/check flow — which every provider accepts.
"""

# Groq's multimodal model. Overridable per-request via the "vision_model" field.
GROQ_VISION_MODEL = "qwen/qwen3.6-27b"

TRANSCRIBE_PROMPT = (
    "Transcribe the question in this image as plain text. "
    "Include every number, symbol, equation, and label exactly as written — "
    "use LaTeX notation for any mathematics. "
    "If the image contains a diagram or graph, describe it in one sentence after the question text. "
    "Output only the transcription, with no preamble and no attempt to answer."
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

def transcribe(b64: str, name: str = "image.png", provider: str = "ollama",
               model: str = "gemma4", host: str = "http://localhost:11434",
               api_key: str = "", vision_model: str = "") -> str:
    """Return a text transcription of the question in a base64-encoded image."""
    if provider == "groq":
        return _groq_transcribe(b64, name, vision_model or GROQ_VISION_MODEL, api_key)

    from ollama import Client as OllamaClient
    client = OllamaClient(host=host)
    messages = [{"role": "user", "content": TRANSCRIBE_PROMPT, "images": [b64]}]
    return drop_reasoning(client.chat(model=model, messages=messages).message.content)

def _groq_transcribe(b64: str, name: str, vision_model: str, api_key: str) -> str:
    from groq import Groq
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=vision_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": TRANSCRIBE_PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:{_mime_for(name)};base64,{b64}"}},
            ],
        }],
    )
    return drop_reasoning(response.choices[0].message.content)
