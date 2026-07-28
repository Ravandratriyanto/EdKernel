import chromadb
from chromadb.utils import embedding_functions

def retrieve(query: str, n_results: int = 3, collection_name: str = "reference", db_path: str = "data/chroma") -> list[str]:
    client = chromadb.PersistentClient(path=db_path)
    ef = embedding_functions.DefaultEmbeddingFunction()
    collection = client.get_or_create_collection(name=collection_name, embedding_function=ef)

    results = collection.query(query_texts=[query], n_results=n_results)
    return results["documents"][0]
