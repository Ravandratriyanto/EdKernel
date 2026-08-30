import threading
import os
import chromadb
from chromadb.utils import embedding_functions

_lock = threading.Lock()
_clients: dict = {}


def _client_and_ef(db_path: str):
    
    with _lock:
        if db_path not in _clients:
            _clients[db_path] = (chromadb.PersistentClient(path=db_path),
                                 embedding_functions.DefaultEmbeddingFunction())
        return _clients[db_path]
MAX_DISTANCE = 0.60


def retrieve(query: str, n_results: int = 3, collection_name: str = "reference", db_path: str = os.getenv("CHROMA_DIR", "data/chroma"), max_distance: float = MAX_DISTANCE, with_sources: bool = False):
    
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
