from core.llm.client import generate

NOTES_PROMPT = """You are a study-notes generator for a student revising for exams.
Turn the SOURCE below into clear, structured revision notes in Markdown.

Rules:
- Open with a one-line summary of what the material covers.
- Use ## headings per topic and bullet points for the key facts.
- Bold key terms. Keep every definition, formula, and date from the source.
- Write maths in LaTeX: inline with single dollars, display on its own line with double dollars.
- Do NOT invent anything not in the source. If the source is thin, keep the notes short.
- End with a "## Key things to remember" section of 3-6 bullets.

SOURCE (__SRC__):
__TEXT__"""

def notes_from_text(text: str, source: str = "document", **llm) -> str:
    text = (text or "").strip()
    if len(text) < 40:
        raise ValueError("Not enough text to make notes from")
    prompt = NOTES_PROMPT.replace("__SRC__", source).replace("__TEXT__", text[:14000])
    return str(generate(prompt, **llm)).strip() 