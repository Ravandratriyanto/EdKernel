import os
import chromadb
from chromadb.utils import embedding_functions

def ingest(folder: str, collection_name: str = "reference", db_path: str = "data/chroma"):
    client = chromadb.PersistentClient(path=db_path)
    ef = embedding_functions.DefaultEmbeddingFunction()
    collection = client.get_or_create_collection(name=collection_name, embedding_function=ef)

    for filename in os.listdir(folder):
        if not filename.endswith(".txt"):
            continue
        filepath = os.path.join(folder, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()

        chunks = [text[i:i+500] for i in range(0, len(text), 500)]
        ids = [f"{filename}_{i}" for i in range(len(chunks))]
        collection.upsert(documents=chunks, ids=ids)
        print(f"Ingested {filename} ({len(chunks)} chunks)")
