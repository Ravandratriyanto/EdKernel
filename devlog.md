# Devlog — SAT/A-level LLM Tutor

## Session 1 — 2026-07-27

### Phase 1 — LLM Connection
- Created `llm/client.py` with a single `generate(prompt, model, host) -> str` function using the Ollama Python client
- Tested against local Ollama instance running gemma4
- Confirmed text in, text out works end to end

### Storage fix
- Ollama was defaulting model storage to `C:\Users\ASUS\.ollama` (only 24GB free on C)
- Moved `.ollama` to `D:\ollama` (125GB free)
- Set `OLLAMA_HOME=D:\ollama` and `OLLAMA_MODELS=D:\ollama\models` as user env vars
- Created a junction symlink `C:\Users\ASUS\.ollama -> D:\ollama` since Ollama ignores env vars for its key files
- Pulled gemma4 to D drive successfully

### Phase 2 — CLI + Check Mode
- Completed `main.py` with argparse for `learn`/`check` modes, `--text`, `--answer`, `--ollama-host`, `--model`
- Check mode sends question + student answer to the model and prints verdict
- Tested: `python main.py check --text "What is the powerhouse of the cell?" --answer "mitochondria"` — passed

### Phase 3 — RAG Grounding
- Created `rag/ingest.py` — loads `.txt` files from a folder, chunks them (500 chars), embeds and upserts into a ChromaDB collection
- Created `rag/retrieve.py` — queries the collection and returns top-N relevant chunks
- Wired retrieval into check mode: relevant context is prepended to the prompt before asking the model
- Created `data/reference/biology.txt` as a sample reference file covering mitochondria, triangle area, photosynthesis, Newton's second law, quadratic formula
- Fixed several issues caught during review: typos in ChromaDB client name, wrong embedding function call, broken indentation, files placed in wrong directories, missing `data/reference` folder

### Current state
- Phases 1, 2, 3 complete
- Phase 4 (learn mode — step-by-step teaching loop) is next
- Plan to test on remote GPU once prompts get heavier in later phases
