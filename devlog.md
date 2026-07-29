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

---

## Session 2 — 2026-07-29

### Phase 4 — Interactive Learn Mode (CLI)
- Implemented `learn_mode()` in `main.py`: builds a message history, calls `chat()` in a loop, prints tutor response, reads student input, appends both to history, stops when model says "Topic complete."
- Wired RAG context into learn mode the same way as check mode — relevant chunks prepended to the first user message
- Fixed `SyntaxError: f-string expression part cannot include a backslash` (Python 3.11 restriction): extracted `context_prefix` into a plain variable before using it in the f-string

### Web UI (Flask + single-file frontend)
- Created `app.py` serving a Flask backend with `/api/start` and `/api/reply` endpoints
- Stateless API design: client sends full message history with every request; server is stateless
- Created `static/index.html` — single-file frontend with:
  - Learn / Check mode toggle
  - Chat bubbles with markdown rendering (marked.js) and math rendering (KaTeX)
  - Auto-detection of ` ```mermaid ` blocks — rendered in-browser using Mermaid.js v11 (ESM)
  - Socratic tutor system prompt enforcing 1-2 sentence responses with a question each turn

### Groq Integration (speed fix)
- Local Ollama (gemma4) was running at ~6 tokens/sec — too slow for interactive use
- Added Groq API support in `llm/client.py`: `_groq_chat()` strips image data (Groq text models don't support multimodal) and calls `groq.Groq().chat.completions.create()`
- Added `provider` parameter to `generate()` and `chat()` — defaults to `"ollama"`, set to `"groq"` to use the cloud LPU
- Added provider/model/API key inputs to the frontend; Groq with `llama-3.3-70b-versatile` runs at 300-500+ tokens/sec
- Added `groq` to `requirements.txt`

### File Attachments (PDF + Image)
- Added `/api/upload` endpoint: detects `.pdf` (extracts text via pypdf, capped at 8000 chars) or image (base64-encodes and returns as data URI)
- Added `📎` button to frontend; attachment preview shown in chat before sending
- `_apply_attachment()` helper appends PDF text or image data to the user message depending on provider
- Ollama supports native image input via `"images"` key; Groq text models only get a text note "(Student attached image: filename)"
- Added `pypdf` to `requirements.txt`

### Graph Generation (Matplotlib + Mermaid)
- Problem: model was trying to use Mermaid for math function plots (it can't draw axes or curves)
- Solution: gave the model two distinct tools:
  - ` ```mermaid ` — for flowcharts, cycles, cause-effect diagrams
  - ` ```graph ` — a plain-English description of what to plot; frontend intercepts this and POSTs to `/api/graph`
- `/api/graph` endpoint: LLM receives the description + `GRAPH_SYSTEM_PROMPT`, generates raw Python matplotlib code, then the server runs it via `exec(code, {"plt": plt, "np": np})` and captures the output to `io.BytesIO()`, returning a base64 PNG
- `GRAPH_SYSTEM_PROMPT` enforces: no imports, no `plt.show/savefig/close`, end with `plt.tight_layout()`, use r-string LaTeX notation for all labels (`r'$f(x) = x^{2}$'`) so superscripts render correctly
- Regex strips any accidental markdown fences, `plt.savefig/show/close` calls, and `import` statements from generated code before exec

### Fixes along the way
- **Mermaid "Syntax error in text"** popup: model generated unquoted special characters in node labels. Fixed: system prompt now requires double-quoted labels (`A["Step one"] --> B["Step two"]`); frontend also suppresses Mermaid error overlays and falls back to showing raw code on parse failure
- **ERR_CONNECTION_RESET on `/api/graph`**: original approach used `subprocess.run()` to call a separate Python process — Flask debug reloader conflicted with it and `"python"` wasn't reliably on PATH on Windows. Fixed: switched entirely to in-process `exec()` with BytesIO capture, no subprocess
- **`^` instead of superscript in graph labels**: matplotlib needs LaTeX mode. Fixed by updating `GRAPH_SYSTEM_PROMPT` to require r-string LaTeX in all labels, and adding a regex to strip any stray `import` lines the model accidentally outputs (which could re-import matplotlib with a different backend)
- **API key exposed in chat**: Groq key was pasted in conversation. Key revoked; new key generated at console.groq.com

### start.bat
- Created `start.bat` to launch Ollama and Flask in separate terminal windows, wait for services to start, then open the browser at `http://localhost:5000`

### Current state
- All endpoints working: learn, reply, check, upload, graph
- Groq provider at 300-500+ t/s makes the tutor feel real-time
- Mermaid flowcharts and matplotlib graphs both rendering in chat
- Pushed to GitHub: https://github.com/Ravandratriyanto/OLLM
- Known issue: occasional "Failed to fetch" on `/api/graph` — likely matplotlib thread-safety with Flask dev server; `use_reloader=False` is a candidate fix
- Next phases planned: hint escalation (3 wrong answers → 3 increasingly specific hints), image input for learn/check, video input

---

## Session 3 — 2026-07-29

### Phase 5 — Escalating hints (written up late; shipped in `5823248`)
- `/api/reply` takes a `wrong_streak` from the client and injects a `[Tutor note: ...]` into the user message: 1× = slightly more specific clue, 2× = name the key concept, 3+ = explain it outright then ask them to apply it
- `TUTOR_SYSTEM_PROMPT` requires every evaluation to end with `[CORRECT]` or `[WRONG]`; `_strip_signal()` pulls that marker off before the text reaches the UI
- Frontend keeps the streak: reset to 0 on `correct === true`, `+= 1` on `false`

### Linux support
- Repo cloned to Linux; `start.bat` has no portable equivalent (`start "..." cmd /k` spawns named terminal windows)
- Added `start.sh`: backgrounds Ollama and Flask to `.logs/`, polls ports for readiness instead of fixed `timeout /t` sleeps, picks up `.venv/bin/python`, skips Ollama when absent or already running, traps signals to kill children
- `.gitignore`: dropped `"D:OLLMstatic"/` (unmatchable off Windows), added `.venv/` and `.logs/`

### Phase 6 — Image input (web app)
- Problem: `_apply_attachment()` only passed images to Ollama. On Groq — now the default provider for speed — the image was dropped and replaced with a bare "(Student attached image: x.png)" note, so the model was told an image existed but never saw it. In `/api/check` it was dropped entirely, not even a note
- Built `vision/image_handler.py` with `transcribe(b64, name, provider, ...) -> str`: Groq goes through `qwen/qwen3.6-27b` using the `image_url` + base64 data URI format (20MB / 5 images per request per Groq docs); Ollama uses its native `images` key
- Transcription prompt demands verbatim numbers/symbols in LaTeX, a one-sentence description for diagrams, and no attempt to answer the question
- Wired into `/api/start`, `/api/reply`, and `/api/check`. Ollama keeps the native image path unchanged; every other provider gets the transcription inlined into the message text
- `vision_model` is overridable per-request, defaulting to `GROQ_VISION_MODEL`
- Failures degrade gracefully: a failed transcription logs a warning and falls back to "(Student attached image: x.png — could not be read: ...)" rather than 500ing the request
- Still outstanding for Phase 6: the `--image` flag in `main.py` (CLI path untouched)

### Clipboard paste for images
- Extracted `uploadFile(file, target)` out of `handleFileChange()` so the 📎 picker and the clipboard share one upload path
- Document-level `paste` listener grabs the first `kind === 'file'` image item; a plain text paste is left alone (no `preventDefault`) so typing is unaffected
- `/api/upload` decides image-vs-PDF by filename extension, but clipboard blobs usually arrive without a usable name — so the handler synthesizes `pasted-<timestamp>.<ext>` from the blob's MIME type to get past the `ALLOWED_IMAGES` check
- `activeAttachTarget()` picks the strip that's actually visible: check panel in check mode, otherwise answer row mid-lesson or topic row before a lesson starts
- Known edge: an exotic clipboard type (e.g. AVIF) falls back to a `.png` name, so the data URI would claim `image/png` for non-PNG bytes and the vision model would likely reject it
