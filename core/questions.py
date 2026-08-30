import base64
import io
import re
import json

import fitz
from pypdf import PdfReader


def _pages_via_vision(pdf_bytes: bytes, **llm) -> str:
    from core.vision.image_handler import transcribe
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texts = []
    for page in doc:
        pix = page.get_pixmap(dpi=150)
        b64 = base64.b64encode(pix.tobytes("jpeg")).decode()
        text = transcribe(b64, name=f"page{page.number}.jpg", **llm).strip()
        if text:
            texts.append(text)
    return "\n\n".join(texts)


def extract_from_paper(pdf_bytes: bytes, vision: bool = False, **llm) -> list[dict]:
    if vision:
        full_text = _pages_via_vision(pdf_bytes, **llm)
    else:
        reader    = PdfReader(io.BytesIO(pdf_bytes))
        full_text = "\n\n".join(p.extract_text() or "" for p in reader.pages)
        if len(full_text.strip()) < 100:
            full_text = _pages_via_vision(pdf_bytes, **llm)

    if len(full_text.strip()) < 100:
        raise ValueError("Could not extract text — may be scanned or maths-heavy")

    prompt = (
        "Output valid JSON only — no prose, no markdown fences.\n\n"
        "Extract every question from this exam paper. Copy verbatim. "
        "If a question has numerical values or named variables, change them to "
        "different plausible values. Ignore rubrics and cover pages. "
        'Return a JSON array. Each element: {"question": "...", "answer": null}. '
        "Populate answer if a mark scheme is present.\n\n"
        f"PAPER TEXT:\n{full_text[:14000]}"
    )

    from core.llm.client import generate
    raw = generate(prompt, **llm)
    m   = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        raise ValueError("LLM did not return a JSON array")
    return json.loads(m.group())
