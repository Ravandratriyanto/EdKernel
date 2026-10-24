import json
from pathlib import Path
BANK_DIR = Path(__file__).parent / 'curricula'

def path_for(curriculum_id: str) -> Path:
    return BANK_DIR / curriculum_id / 'quizzes.json'

def load(curriculum_id: str) -> list[dict]:
    path = path_for(curriculum_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return []
    return data if isinstance(data, list) else []
def names(curriculum_id: str) -> list[str]:
    return list(dict.fromkeys(q.get('quiz') or 'Quiz' for q in load(curriculum_id)))
def load_quiz(curriculum_id: str, name: str='') -> list[dict]:
    quizzes = names(curriculum_id)
    if name not in quizzes:
        name = quizzes[0] if quizzes else ''
    return [q for q in load(curriculum_id) if (q.get('quiz') or 'Quiz') == name]
def pick(curriculum_id: str, n: int=5) -> list[dict]:
    return load(curriculum_id)[:n]