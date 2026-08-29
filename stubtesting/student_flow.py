import os
import json 
import sys 
from pathlib import Path 
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.llm.client import generate
from core.prompts import build_tutor_prompt
from dotenv import load_dotenv 
load_dotenv()
DEMO = Path(__file__).parent.parent / "curricula" / "demo"

def load(fname):
    return json.loads((DEMO / fname).read_text())


def pick(label, items, key="name"):
    print(f"\n── {label} ──")
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item[key]}")
    while True:
        try:
            return items[int(input("Pick number: ")) - 1]
        except (ValueError, IndexError):
            print("Try again.")


def main():
    topics    = load("topics.json")
    questions = load("questions.json")

    topic = pick("Topics", topics)
    topic_name = topic["name"]

    tq = [q for q in questions if q["topic"] == topic_name]
    if not tq:
        print(f"No questions for {topic_name} yet.")
    else:
        q = pick("Questions", tq, key="question")
        print(f"\nQuestion: {q['question']}")
        student_answer = input("Your answer: ").strip()

        prompt = (
            f"Topic: {topic_name}\n"
            f"Question: {q['question']}\n"
            f"Model answer: {q['answer']}\n"
            f"Student answered: {student_answer}\n\n"
            "Give brief Socratic feedback. Do not reveal the full answer outright."
        )
        system = build_tutor_prompt(flavour="introductory computer science exam preparation")
        from core.llm.client import chat
        reply = chat(
            [{"role": "system", "content": system},
             {"role": "user",   "content": prompt}],
            model="openai/gpt-oss-120b", provider="groq",
            api_key=os.environ.get("API_KEY", ""),
        )
        print(f"\nTutor: {reply}\n")

    # Student adds their own question
    print("── Add your own question ──")
    own_q = input("Your question: ").strip()
    own_a = input("Your answer:   ").strip()
    if own_q and own_a:
        import secrets, time
        questions.append({
            "id": secrets.token_hex(6),
            "topic": topic_name,
            "question": own_q,
            "answer": own_a,
            "type": "short_answer",
            "created_by": 0,
            "created_at": int(time.time()),
        })
        (DEMO / "questions.json").write_text(json.dumps(questions, indent=2))
        print("Question saved — future students will see it.")


if __name__ == "__main__":
    main()