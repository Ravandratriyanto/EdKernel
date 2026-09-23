import json
from pathlib import Path
CURRICULA_DIR = Path(__file__).parent / 'curricula'
DEFAULT_REFERENCE_DIR = 'data/reference'
DEFAULT_PAPERS_DIR = 'data/papers'

def load(curriculum_id: str) -> dict:
    path = CURRICULA_DIR / curriculum_id / 'manifest.json'
    if not path.exists():
        raise FileNotFoundError(f"No curriculum '{curriculum_id}' — expected manifest at {path}")
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        raise ValueError(f"manifest.json for '{curriculum_id}' is not valid JSON: {e}")
    missing = {'id', 'name', 'prompt_flavour', 'collection'} - manifest.keys()
    if missing:
        raise ValueError(f"manifest.json for '{curriculum_id}' is missing: {', '.join(sorted(missing))}")
    return manifest

def list_curricula() -> list[str]:
    if not CURRICULA_DIR.exists():
        return []
    return sorted((p.name for p in CURRICULA_DIR.iterdir() if p.is_dir() and (p / 'manifest.json').exists()))

def reference_dir(manifest: dict) -> str:
    return manifest.get('reference_dir', DEFAULT_REFERENCE_DIR)

def papers_dir(manifest: dict) -> str:
    return manifest.get('papers_dir', DEFAULT_PAPERS_DIR)