"""Quick diagnostic: hit the model with no tutor prompt and see if it can reason correctly.

    python evals/raw_model_test.py

Compare this output against the tutor to isolate whether failures are:
  - model capability (raw gets it wrong too) → can't fix with prompting
  - prompt interference (raw gets it right, tutor doesn't) → fixable
"""

import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.environ["API_KEY"])
MODEL = "openai/gpt-oss-120b"

QUESTIONS = [
    ("weighted average",
     "An element has two isotopes: mass 10 at 75% abundance and mass 14 at 25% abundance. "
     "What is the average atomic mass? Show every step."),

    ("percentage change",
     "A phone costs £200 and drops to £170. What is the percentage decrease? Show every step."),

    ("linear equation",
     "Solve for x: 5x - 3 = 22. Show every step."),

    ("CORRECT signal — right answer",
     "A student was asked: 'Solve for x: 3x + 7 = 22'. The student replied: 'x = 5'. "
     "Is the student correct? Say CORRECT or WRONG and show the check."),

    ("WRONG signal — wrong answer",
     "A student was asked: 'Solve for x: 2x - 4 = 10'. The student replied: 'x = 3'. "
     "Is the student correct? Say CORRECT or WRONG and show the check."),

    ("OPEN signal — opinion question",
     "A student asked: 'Which is more important in maths — algebra or geometry?' "
     "Does this question have one right answer, or is it open to opinion? "
     "If open, say OPEN at the end."),

    ("answer leak guard",
     "A student asked: 'What is 30% of 80?' — without giving the answer, "
     "write one Socratic question to guide them toward it."),
]


def ask(question: str) -> str:
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": question}],
        timeout=30.0,
    )
    return r.choices[0].message.content.strip()


def main():
    sep = "─" * 60
    for label, question in QUESTIONS:
        print(f"\n{sep}")
        print(f"TEST: {label}")
        print(f"Q: {question}")
        print(f"{sep}")
        try:
            answer = ask(question)
            print(answer)
        except Exception as e:
            print(f"ERROR: {e}")
    print(f"\n{sep}")


if __name__ == "__main__":
    main()
