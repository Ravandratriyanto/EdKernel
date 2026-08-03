"""Pick the worked examples closest to what was asked, and show them to the model.

The model does not get exam conventions wrong for lack of subject knowledge — it
gets them wrong because nothing in the prompt shows it what the convention looks
like. Measured over 20 generations of four economics diagrams: 7/20 had demand
and supply the right way up without examples, 20/20 with them.

So subjects are data. Adding statistics means adding entries to
diagram_examples.py; it never means another module like this one.

Examples are embedded in memory on first use rather than kept in Chroma. The
reference collection sat silently empty for three sessions because building it
was a separate step somebody had to remember. There is no step to forget here.
"""
import numpy as np
from chromadb.utils import embedding_functions

from diagram_examples import EXAMPLES

# Cosine similarity, so 1.0 is identical and 0.0 unrelated — the opposite
# direction to rag/retrieve.py's distance. Below this, nothing is close enough
# to help and an example would only mislead. Measured: "plot f(x) = x^2 and its
# derivative" falls under it and gets no examples, which is what keeps this off
# the existing maths path.
MIN_SIMILARITY = 0.35

DEFAULT_K = 2

_cache = None


def _load():
    """Examples plus unit-length embeddings of their descriptions, built once."""
    global _cache
    if _cache is None:
        ef = embedding_functions.DefaultEmbeddingFunction()
        vecs = np.array(ef([e["description"] for e in EXAMPLES]), dtype=float)
        # Divide each row by its own length, so a dot product IS the cosine.
        # keepdims=True keeps the result a column, so it broadcasts down rows.
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        _cache = (vecs, ef)
    return _cache


def find_shots(description: str, k: int = DEFAULT_K,
               min_similarity: float = MIN_SIMILARITY) -> list[dict]:
    """The closest worked examples, or [] when nothing is close enough."""
    try:
        vecs, ef = _load()
        q = np.array(ef([description])[0], dtype=float)
    except Exception:
        return []          # never cost a student a graph over this

    q /= np.linalg.norm(q)
    sims = vecs @ q
    # argsort is ascending, so reverse it to get best-first.
    order = np.argsort(sims)[::-1][:k]
    return [EXAMPLES[i] for i in order if sims[i] >= min_similarity]


def shot_messages(description: str, **kw) -> list[dict]:
    """Worked examples as prior turns of the conversation.

    Real user/assistant exchanges rather than text pasted into the system
    prompt: the model is asked to continue a pattern it appears to have already
    followed, which lands harder than being told about it.
    """
    messages = []
    for shot in find_shots(description, **kw):
        messages.append({"role": "user",
                         "content": f"Generate a graph for: {shot['description']}"})
        messages.append({"role": "assistant", "content": shot["code"]})
    return messages
