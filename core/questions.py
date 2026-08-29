import io
import re
import json

from pypdf import PdfReader


def extract_from_paper(pdf_bytes: bytes, **llm) -> list[dict]:
    reader    = PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n\n".join(p.extract_text() or "" for p in reader.pages)
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
