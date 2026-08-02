import chromadb
from chromadb.utils import embedding_functions

# Cosine distance: 0 is identical, 1 is unrelated.
#
# Calibrated over 20 topics the corpus covers and 10 it does not. The two
# classes OVERLAP — the worst real topic ("big O notation", 0.605) scores
# further away than the best unrelated one ("history of jazz", 0.495, which
# genuinely matches an SAT reading passage about jazz tap). So no threshold
# separates them cleanly and this number is a compromise, not a clean cut:
# 0.60 keeps 19 of 20 real topics and admits 1 of 10 unrelated ones.
#
# It still earns its place. Without it Chroma returns its n nearest neighbours
# however far away they are, so a maths lesson gets biology chunks prepended
# as "Reference material:".
MAX_DISTANCE = 0.60


def retrieve(query: str,
             n_results: int = 3,
             collection_name: str = "reference",
             db_path: str = "data/chroma",
             max_distance: float = MAX_DISTANCE,
             with_sources: bool = False):
    """Relevant reference chunks, or [] when nothing is close enough.

    Returning [] is the safe outcome: app.py builds an empty context_prefix and
    the tutor runs ungrounded, exactly as it did before this collection existed.
    """
    client = chromadb.PersistentClient(path=db_path)
    ef = embedding_functions.DefaultEmbeddingFunction()
    try:
        collection = client.get_collection(name=collection_name,
                                           embedding_function=ef)
    except Exception:
        return []          # never ingested — do not take a lesson down for it

    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "distances", "metadatas"],
    )
    docs = results["documents"][0]
    dists = results["distances"][0]
    metas = results["metadatas"][0]

    kept = [(d, m, dist) for d, m, dist in zip(docs, metas, dists)
            if dist <= max_distance]
    if with_sources:
        return [{"text": d, "source": m.get("source", ""),
                 "page": m.get("page", 0), "distance": round(dist, 3)}
                for d, m, dist in kept]
    return [d for d, _, _ in kept]
