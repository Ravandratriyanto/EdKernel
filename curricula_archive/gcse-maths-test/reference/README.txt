# Test Materials — Drive sync seed set

Four plain-text GCSE Maths reference notes, written to match the handwriting in
the vision eval samples (evals/vision_samples/v1-v9): linear equations,
expanding brackets, factorising quadratics.

Purpose: seed a Google Drive folder with these to test the drive_sync wrapper.
The wrapper's job is to download a Drive folder's files into
curricula/<cid>/reference/ and then call the existing ingest pipeline
(core/rag/ingest.build via app.py _start_ingest).

Format note: the ingest pipeline reads *.txt via _collect_texts() and *.pdf
(with optional .json sidecar) via _collect_pdfs(). Plain .txt needs no PDF
tooling, so these ingest as-is. Each file is chunked at ~900 chars.

These are test fixtures, not the real gcse-maths curriculum — keep them separate.
