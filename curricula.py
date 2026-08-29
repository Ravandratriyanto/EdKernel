"""Load curriculum manifests.

A manifest lives at curricula/<id>/manifest.json and describes one subject
instance: its name, the reference material that feeds RAG, and the flavour
text that shapes the tutor's persona for that subject.

Required manifest fields:
  id              matches the directory name
  name            display name shown in the UI
  prompt_flavour  replaces the hardcoded "SAT/A-level" in system prompts
  collection      ChromaDB collection name (one per curriculum)

Optional:
  level           e.g. "secondary", "undergraduate"
  subjects        list of subject areas covered
  tutor_style     e.g. "Socratic"
  reference_dir   path to .txt notes (default: data/reference)
  papers_dir      path to past-paper PDFs (default: data/papers)
"""

import json
from pathlib import Path

CURRICULA_DIR = Path(__file__).parent / "curricula"
DEFAULT_REFERENCE_DIR = "data/reference"
DEFAULT_PAPERS_DIR = "data/papers"


def load(curriculum_id: str) -> dict:
    """Return the manifest for a curriculum id.

    Raises FileNotFoundError if the curriculum directory does not exist.
    Raises ValueError if manifest.json is malformed or missing required fields.
    """
    path = CURRICULA_DIR / curriculum_id / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No curriculum '{curriculum_id}' — expected manifest at {path}"
        )
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"manifest.json for '{curriculum_id}' is not valid JSON: {e}")

    missing = {"id", "name", "prompt_flavour", "collection"} - manifest.keys()
    if missing:
        raise ValueError(
            f"manifest.json for '{curriculum_id}' is missing: {', '.join(sorted(missing))}"
        )
    return manifest


def list_curricula() -> list[str]:
    """All curriculum IDs available on disk, sorted."""
    if not CURRICULA_DIR.exists():
        return []
    return sorted(
        p.name for p in CURRICULA_DIR.iterdir()
        if p.is_dir() and (p / "manifest.json").exists()
    )


def reference_dir(manifest: dict) -> str:
    return manifest.get("reference_dir", DEFAULT_REFERENCE_DIR)


def papers_dir(manifest: dict) -> str:
    return manifest.get("papers_dir", DEFAULT_PAPERS_DIR)
