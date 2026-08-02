"""Build the reference collection from .txt notes and past-paper PDFs.

Run directly to rebuild from scratch:

    python -m rag.ingest
"""

import glob
import json
import logging
import re
import warnings
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
from pypdf import PdfReader

# pypdf is loud about malformed cross-reference tables in scanned papers, and
# every one of those warnings is about a file we are about to skip anyway.
warnings.filterwarnings("ignore")
logging.getLogger("pypdf").setLevel(logging.CRITICAL)

DB_PATH = "data/chroma"
COLLECTION = "reference"

# Punctuation that belongs in real prose. Anything else counts towards the junk
# score — chart pages extract as ASCII art and are almost all box-drawing.
_OK_PUNCT = ".,;:!?'\"()-%$/=+"
_MAX_JUNK = 0.08     # measured: real pages sit far below this, charts far above
_MIN_PAGE = 200      # chars; shorter than this is a header or a blank scan
_MIN_CHUNK = 120


def _junk_ratio(s: str) -> float:
    """Share of characters that are not letters, digits, space or normal punctuation."""
    if not s:
        return 1.0
    bad = sum(1 for c in s if not (c.isalnum() or c.isspace() or c in _OK_PUNCT))
    return bad / len(s)


def _page_texts(pdf_path: str):
    """Yield (page number, text) and survive errors raised part-way through.

    `reader.pages` is lazy, so an encrypted or corrupt page raises when it is
    reached, not when the file is opened. A plain `for page in reader.pages`
    therefore throws out of the middle of the loop. Indexing one page at a time
    inside its own try lets us keep whatever was readable before the failure.
    """
    try:
        reader = PdfReader(pdf_path)
        n = len(reader.pages)
    except Exception:
        return
    for i in range(n):
        try:
            yield i, (reader.pages[i].extract_text() or "")
        except Exception:
            return          # abandon the rest of this file, keep what we have


def _chunk(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """Split into chunks that end on sentence boundaries.

    The old version sliced every 500 characters regardless of content, which
    cuts mid-sentence and mid-equation. Half an equation embeds as noise.
    """
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    parts, buf = [], ""
    # (?<=[.!?]) is a lookbehind: split *after* a sentence-ending mark without
    # consuming it, so the punctuation stays attached to the sentence.
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(buf) + len(sentence) + 1 > size and buf:
            parts.append(buf.strip())
            buf = buf[-overlap:] + " " + sentence   # carry context across the seam
        else:
            buf += (" " if buf else "") + sentence
    if buf.strip():
        parts.append(buf.strip())
    return [p for p in parts if len(p) > _MIN_CHUNK]


def _collect_pdfs(folder: str) -> tuple[list, list, list]:
    docs, ids, metas = [], [], []
    for pdf in sorted(glob.glob(f"{folder}/*.pdf")):
        sidecar = Path(pdf.replace(".pdf", ".json"))
        title = "unknown"
        if sidecar.exists():
            try:
                title = json.loads(sidecar.read_text()).get("title", "unknown")
            except (ValueError, OSError):
                pass
        stem = Path(pdf).stem
        kept = 0
        for pageno, text in _page_texts(pdf):
            text = text.strip()
            if len(text) < _MIN_PAGE or _junk_ratio(text) > _MAX_JUNK:
                continue
            for k, chunk in enumerate(_chunk(text)):
                docs.append(chunk)
                ids.append(f"{stem}_p{pageno}_{k}")
                metas.append({"source": title[:80], "page": pageno})
                kept += 1
        print(f"  {title[:52]:54} {kept:4} chunks")
    return docs, ids, metas


def _collect_texts(folder: str) -> tuple[list, list, list]:
    docs, ids, metas = [], [], []
    for path in sorted(glob.glob(f"{folder}/*.txt")):
        name = Path(path).name
        chunks = _chunk(Path(path).read_text(encoding="utf-8"))
        for k, chunk in enumerate(chunks):
            docs.append(chunk)
            ids.append(f"{name}_{k}")
            metas.append({"source": name, "page": 0})
        print(f"  {name:54} {len(chunks):4} chunks")
    return docs, ids, metas


def build(text_folder: str = "data/reference",
          pdf_folder: str = "data/papers",
          db_path: str = DB_PATH,
          collection_name: str = COLLECTION) -> int:
    """Rebuild the collection from scratch. Returns the document count."""
    client = chromadb.PersistentClient(path=db_path)
    ef = embedding_functions.DefaultEmbeddingFunction()

    # Deleted and recreated rather than get_or_create: the cosine metric is set
    # at creation time and Chroma will not apply it to a collection that exists.
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(
        name=collection_name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},   # bounded 0-1, so one threshold works
    )

    print("reference notes:")
    docs, ids, metas = _collect_texts(text_folder)
    print("past papers:")
    d2, i2, m2 = _collect_pdfs(pdf_folder)
    docs += d2
    ids += i2
    metas += m2

    if not docs:
        print("nothing to ingest")
        return 0

    # Batched because embedding 3000+ chunks in one call is slow to fail and
    # gives no progress. 400 keeps memory flat on an 8GB box.
    for i in range(0, len(docs), 400):
        collection.upsert(documents=docs[i:i + 400],
                          ids=ids[i:i + 400],
                          metadatas=metas[i:i + 400])
        print(f"  embedded {min(i + 400, len(docs))}/{len(docs)}")

    print(f"\ncollection '{collection_name}': {collection.count()} chunks")
    return collection.count()


if __name__ == "__main__":
    build()
