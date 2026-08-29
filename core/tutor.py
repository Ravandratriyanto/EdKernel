from core.prompts import TUTOR_SYSTEM_PROMPT, hint_note, tutor_reply
from core.llm.client import chat


def start(topic: str, context: str = "", question_bank: str = "", **llm) -> dict:
    system = TUTOR_SYSTEM_PROMPT
    if question_bank:
        system += (
            "\n\nQuestion bank for this curriculum (use these when quizzing the student "
            "— present them one at a time, never reveal the answer until the student "
            "has attempted it):\n" + question_bank
        )
    user_content = f"I want to learn about: {topic}"
    if context:
        user_content += f"\n\nReference material:\n{context}"
    messages = [
        {"role": "system",    "content": system},
        {"role": "user",      "content": user_content},
    ]
    raw  = chat(messages, **llm)
    text, correct = tutor_reply(raw)
    messages.append({"role": "assistant", "content": raw})
    return {"reply": text, "correct": correct, "messages": messages}


def reply(messages: list, student_message: str, wrong_streak: int = 0, **llm) -> dict:
    hint    = hint_note(wrong_streak)
    content = student_message + (f"\n\n{hint}" if hint else "")
    msgs    = messages + [{"role": "user", "content": content}]
    raw     = chat(msgs, **llm)
    text, correct = tutor_reply(raw)
    msgs.append({"role": "assistant", "content": raw})
    return {"reply": text, "correct": correct, "messages": msgs}
