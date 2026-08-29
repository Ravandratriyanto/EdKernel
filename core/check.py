from core.prompts import build_check_prompt, strip_signal
from core.llm.client import generate


def run(question: str, answer: str, context: str = "", **llm) -> dict:
    prompt = build_check_prompt(question, answer, context)
    raw    = generate(prompt, **llm)
    text, correct = strip_signal(raw)
    return {"feedback": text, "correct": correct}
