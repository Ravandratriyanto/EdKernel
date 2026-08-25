import threading

import chromadb
from chromadb.utils import embedding_functions

_lock = threading.Lock()
_clients: dict = {}


def _client_and_ef(db_path: str):
    """One Chroma client and one embedding model per path, built once.

    PersistentClient is not safe to build from two threads at once: the second
    one runs _release_system and deletes the first's Rust bindings mid-use,
    which surfaces as "Could not connect to tenant default_tenant". Flask
    serves requests on threads, so the web app could hit this too — it was
    found by running the evals 2 at a time.

    Building once also stops reloading the ONNX embedding model on every
    single question, which was pure waste.

    The collection itself is fetched per call, not cached, so a collection
    created after startup is still picked up.
    """
    with _lock:
        if db_path not in _clients:
            _clients[db_path] = (chromadb.PersistentClient(path=db_path),
                                 embedding_functions.DefaultEmbeddingFunction())
        return _clients[db_path]













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
    client, ef = _client_and_ef(db_path)
    try:
        collection = client.get_collection(name=collection_name,
                                           embedding_function=ef)
    except Exception:
        return []          

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
