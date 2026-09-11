"""Per-curriculum quiz banks — curricula/<id>/quizzes.json.

Separate from questions.json on purpose. The tutor gets questions.json injected
into its system prompt *with the answers*, which is right for a tutor and wrong
for a quiz: anything in that file is one prompt-injection away from the student.
Quiz keys live here, are read server-side only, and never reach the browser
before the attempt is submitted.

Shape:
    [
      {"id": "gm1",
       "text": "Simplify ...",
       "options": [{"letter": "A", "text": "..."}, ...],
       "answer": "B",
       "working": "..."}
    ]
"""
import json
from pathlib import Path

BANK_DIR = Path(__file__).parent / "curricula"


def path_for(curriculum_id: str) -> Path:
    return BANK_DIR / curriculum_id / "quizzes.json"


def load(curriculum_id: str) -> list[dict]:
    """Every quiz question for a curriculum, or [] if it has no bank yet."""
    path = path_for(curriculum_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def pick(curriculum_id: str, n: int = 5) -> list[dict]:
    """The first n questions from the bank, key included. Server-side only."""
    return load(curriculum_id)[:n]
