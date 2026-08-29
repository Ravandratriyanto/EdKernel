#!/bin/bash
set -e
cd "$(dirname "$0")"

# Kill anything already on port 5000
fuser -k 5000/tcp 2>/dev/null || true

source .venv/bin/activate
python stubtesting/seed.py
python -m rag.ingest --curriculum demo
python app.py
