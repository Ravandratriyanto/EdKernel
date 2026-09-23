import numpy as np
from chromadb.utils import embedding_functions
from diagram_examples import EXAMPLES
MIN_SIMILARITY = 0.35
DEFAULT_K = 2
_cache = None

def _load():
    global _cache
    if _cache is None:
        ef = embedding_functions.DefaultEmbeddingFunction()
        vecs = np.array(ef([e['description'] for e in EXAMPLES]), dtype=float)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        _cache = (vecs, ef)
    return _cache

def find_shots(description: str, k: int=DEFAULT_K, min_similarity: float=MIN_SIMILARITY) -> list[dict]:
    try:
        vecs, ef = _load()
        q = np.array(ef([description])[0], dtype=float)
    except Exception:
        return []
    q /= np.linalg.norm(q)
    sims = vecs @ q
    order = np.argsort(sims)[::-1][:k]
    return [EXAMPLES[i] for i in order if sims[i] >= min_similarity]

def shot_messages(description: str, **kw) -> list[dict]:
    messages = []
    for shot in find_shots(description, **kw):
        messages.append({'role': 'user', 'content': f"Generate a graph for: {shot['description']}"})
        messages.append({'role': 'assistant', 'content': shot['code']})
    return messages