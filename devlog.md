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

### Plain-language tutor prompt
- The tutor's English was too academic. `app.py` and `main.py` had drifted into two different `TUTOR_SYSTEM_PROMPT`s; both updated
- Rules added: short sentences, everyday words a 12-year-old knows, one idea per sentence, no filler ("let us consider", "it is important to note"), explicit swaps (`use` not `utilise`, `so` not `therefore`, `find` not `determine`), subject terms explained in plain words on first use, and assume English may be the student's second language
- Deliberately a prompt change, not a fine-tune — tone is the wrong reason to train, and prompts iterate in seconds

### Phase A — a transformer from scratch (`training/`)
- `training/train_tiny.py`: complete char-level GPT in one file — tokenizer, causal self-attention, residual blocks, training loop, sampling. No `transformers`, no `Trainer`. Commented to explain *why* (what `is_causal=True` prevents, what the residual `x +` buys)
- Verified on CPU: loss 4.19 → 2.78 in 300 steps on tinyshakespeare; samples show word-length gaps and the `NAME:` speaker format emerging
- Overfitting demo measured, not asserted: training on the 975-byte `biology.txt` drives train loss to 0.90 while val *climbs* to 3.59 (gap +2.69) — the same failure that will bite Phase C if fine-tuned on too few logged sessions
- Fixed a usability bug found while testing: a corpus smaller than `block_size` crashed with an unreadable torch error from inside `get_batch`; now fails early with the actual split size and a working `--block-size` suggestion
- `torch` kept out of the app's `requirements.txt` (multi-GB) — `training/requirements.txt` holds it with both the CPU and CUDA install commands
- `training/data/` and `training/out/` gitignored: the corpus is downloadable and checkpoints are build artifacts
- Note: no GPU on the dev box (`nvidia-smi` finds no driver), so everything above was verified against the CPU wheel

### Deployment thinking (no code yet)
- Decision: rent compute, don't own. School load is ~15% duty cycle (school hours, weekdays, term time), and IB/Cambridge exam calendars are globally synchronised — the entire customer base peaks in the same May fortnight. Size owned capacity to baseline, burst to rented for exam season
- Serving target for a fine-tuned 7-8B: **48GB** (L40S/A6000 class). KV cache is 128 KiB/token for a Llama-3-8B-class model with GQA, so 24GB leaves only ~7 concurrent sessions at 4k context once bf16 weights take 16GB; 48GB gives ~33 at 8k with FP8 weights. Size against 8k, not 4k — PDF attachments cap at 8000 chars and past papers are long
- Use vLLM/SGLang for continuous batching and prefix caching; the latter directly offsets the stateless resend-full-history design
- Blockers for the business model, none of which exist yet: no auth at all (the API key is typed into the browser, so every user brings their own), no per-student metering, no session logging. Billing "reasonable tokens" requires all three

### Current state
- Phases 1–5 complete. Phase 6 complete for the web app; the `--image` flag in `main.py` is the only piece left before it meets the readme's definition of done. Phase 7 (video) untouched
- Runs on Linux via `start.sh`; `start.bat` kept for Windows. Ollama is optional now — with the Groq provider the tutor works with no local model server at all
- Images work on every provider: Ollama natively, everything else through transcription. They can be attached with 📎 or pasted with Ctrl+V
- Training work has its own tree under `training/`, independent of the app. Phase A (from-scratch transformer) runs and is verified; Phases B and C not started

### Known issues / caveats
- **The Groq key still needs rotating.** It was briefly written into `.gitignore` — which does not hide anything, since `.gitignore` is itself tracked and pushed. Caught before any commit, and a full-history scan (`git log --all -p` for `gsk_` + 20 chars) is clean, so nothing ever reached GitHub. The key is still burned: it sat on disk, in editor undo history, and in a chat transcript. Same drill as the Session 2 incident — revoke at console.groq.com and only ever paste the new key into the UI field
- Phase 6 has not been exercised against the live Groq API. The model id and request format come from Groq's vision docs; no real image has round-tripped. Worth one manual test
- Clipboard paste was verified with a stubbed DOM and `node --check`, not a real browser paste event
- An exotic clipboard image type (e.g. AVIF) is named `.png` by the paste handler, so the data URI would mislabel the bytes and the vision model would likely reject it
- The `/api/graph` "Failed to fetch" from Session 2 is believed fixed by `use_reloader=False`, but has not recurred often enough to confirm
- No GPU on the dev box, so all training verification is CPU-only

### Next
1. **Phase B — session logging.** The bottleneck for three separate things at once: the Phase C fine-tuning dataset, per-student token metering for billing, and the auth model the school-subscription plan needs. Every unlogged session is data that cannot be recovered later
2. Server-side session state + prompt caching. `/api/reply` resends the whole history every turn, so input tokens grow quadratically across a session — plausibly a 2–5× cost reduction before any hardware decision
3. Auth: the API key currently lives in the browser, which inverts the intended model. Schools paying for their students requires domain-verified SSO and per-tenant quotas
4. Then Phase C (LoRA fine-tune), Phase 7 (video), and the `--image` CLI flag

## Session 4 — 2026-07-30

Started by pulling `8ef028e` (past-papers mode + multiple-choice option buttons) from the private repo. Everything below is on top of that.

### API keys in `.env`
- Keys were typed into the browser every session and lived nowhere else. `.env` was already in `.gitignore` but nothing read it
- `load_dotenv()` at import; `_key(data, field, env_var)` resolves a key as *UI value wins, `.env` is the fallback*. Wired into all six `api_key` sites and the one `tavily_key` site
- `.env.example` added as the committed template. `python-dotenv` added to `requirements.txt` explicitly — it was already installed, but only as a transitive chromadb dependency, which would break silently if chromadb ever dropped it
- Deliberately a fallback, not a replacement: the UI field still overrides, so a second key can be used without editing files

### `keycheck.py` — key status at launch
- Both `start.sh` and `start.bat` now print which keys `.env` provides before anything starts
- Written once in Python rather than twice in bash + batch: parsing `.env` in batch is genuinely unreliable (undefined `for` tokens expand to literals, CRLF leaves a stray `\r` inside the value). Python is already a hard requirement of both scripts
- No heavy imports (no chromadb) so it stays instant; ASCII-only output so it doesn't throw on a cp437 Windows console
- Values masked to the last 4 characters — `start.sh` output sits in scrollback, and last-4 is enough to confirm *which* key loaded
- `start.sh` calls it after `$PYTHON` is resolved so it uses the venv; `start.bat` uses `"%~dp0keycheck.py"` so it works from any working directory

### Multiple-choice options made optional
- The frontend was already conditional (`if (options.length > 0)`); the mandate was entirely in the prompt — *"Each response must follow this exact structure … exactly 4 multiple-choice options"*
- Rewritten around the **shape of the answer**, not the tutor's judgement. Offer options when the answer is one of a few named things, or the student has been wrong twice on the same idea, or they are too new to the topic to have the words. Do NOT offer them for explain-in-your-own-words, "what do you notice", a calculated number or derived expression, a multi-step method, or a plain affirmation
- The calculation case matters most: four options let a student backsolve by elimination instead of doing the working, which trains the wrong skill for A-level
- Relaxed *exactly 4* → **2 to 4**, so binary judgements get two buttons instead of two padded distractors
- `extractOptions` now requires **≥ 2** matches. Once options are optional, a lone `A) …` line is far more likely to be prose than a choice set — same floor the past-papers parser already used
- Ordering constraint found while doing this: `_SIGNAL_RE` is anchored to end-of-string, so options must sit *before* any `[CORRECT]`/`[WRONG]` marker. The prompt now says so explicitly, otherwise answer tracking breaks silently

### Bug: `[WAITING FOR RESPONSE]` leaking into the UI
- Two causes compounding. `/api/reply` injects `[Tutor note: ...]` into the *user* message, and the reworked prompt put "stop and wait for their answer" next to the `[CORRECT]`/`[WRONG]` instruction. The model generalised the bracket convention and invented its own marker
- `_strip_signal` only matched `[CORRECT]`/`[WRONG]` anchored at end-of-string, so a mid-response marker sailed through to the bubble
- Fixed twice over: `_STRAY_MARKER_RE` drops any all-caps bracket marker on its own line (whatever the model invents), and the prompt names the two permitted markers and bans inventing others
- Anchored per-line so it cannot eat interval notation like `[0, 5]` or an inline `[SI]` — both covered by the test cases
- Regression was self-inflicted, and shipped because the previous prompt change was verified only structurally, never against real model output. Prompt changes need a live turn

### Bug: the tutor ignored direct requests
- Screenshot showed a student asking three times for downloadable papers ("PLEASE FOR GOODNESS SAKE") and getting Socratic questions plus option buttons every time
- `"never give the full answer unprompted"` made every input a lesson turn, including meta-requests that were not about the subject at all
- Prompt now answers out-of-lesson requests plainly in 1–2 sentences, never attaches options to them, states honestly that PDFs are not possible, and repeats the plain answer if asked again rather than steering back into the lesson
- Verified live against `llama-3.3-70b-versatile`, replaying the exact three messages: refuses plainly on both attempts, no invented marker, no options on the meta-turns

### What the Tavily key actually does (investigated, not changed)
- One call to `https://api.tavily.com/search` with `include_domains` restricted to 10 revision sites. Tavily returns a text **snippet** per result in `content`
- `/api/papers` uses only those snippets, capped at 7000 chars, and asks the model to **write new questions** from them
- So the questions students answer are LLM-generated, *not* real past-paper questions — they will not match a real mark scheme, and the answer key is whatever the model asserted. That is a bigger accuracy risk than the missing PDF feature
- No PDF is fetched, stored or served anywhere. The only thing reaching the user is the source URL list rendered as link chips
- Upgrade path if real papers are wanted: `include_raw_content: true` for fuller text (one line), or filter results to `.pdf` URLs and fetch them directly — `pypdf` is already a dependency, so actual questions could be extracted verbatim instead of invented

### Key exposure — third incident
- Both a live Groq key and a live Tavily key were written into `.env.example`, which is **not** gitignored (only `.env` is). Caught before any commit
- Scrubbed back to blanks, real values moved into `.env`, and `.env.example` now carries a header saying it is committed and must never hold a real key
- Full-history scan clean: `git log --all -p` for `gsk_`/`tvly-` + 20 chars finds nothing. The 4 apparent hits are the `placeholder="gsk_..."` attributes in `index.html`
- Both keys are burned regardless — they were on disk in a tracked-file location, in editor undo history, and in a chat transcript. "Never committed" is not "never exposed"
- Pattern worth naming: Session 2 was a key pasted into chat, Session 3 was a key written into `.gitignore`, this is a key written into `.env.example`. Two of three landed in a file git tracks. `.env` + `keycheck.py` give the keys a correct home now, but nothing *stops* a paste into the wrong file — a `pre-commit` hook rejecting `gsk_[A-Za-z0-9]{20,}` / `tvly-[A-Za-z0-9_-]{20,}` in a staged diff would

### Current state
- Past-papers mode works but generates questions rather than serving papers. Options are now optional across the tutor; past-papers MCQs stay mandatory, which is correct for that mode
- Keys can live in `.env` and are reported (masked) at launch on both platforms
- Groq path exercised live this session for the first time in a while — the tutor prompt changes were verified against `llama-3.3-70b-versatile`, not just structurally

### Known issues / caveats
- **Both keys still need rotating.** The Groq key in particular: the live test this session succeeded, which proves it has *not* been revoked. Revoke at console.groq.com and app.tavily.com
- The Session 3 note about the Groq key needing rotation was never actioned — worth checking whether the key exposed this session is the same one
- Past-paper questions are invented by the model from search snippets. No mark-scheme fidelity, and the `[ANSWER: X]` key is the model's own claim
- No downloadable PDFs. The tutor now says so honestly instead of deflecting, but the feature does not exist
- Options behaviour was verified on three meta-turns and by unit-testing the parser; the *conditions* (whether it correctly withholds options on a calculation question mid-lesson) have not been exercised over a long real lesson
- A broken-image placeholder appeared in the UI above a student bubble in this session's screenshot — a failed attachment preview, uninvestigated
- Everything from Session 3's caveat list that was not touched here still stands

### Next
1. Rotate both keys, then add the `pre-commit` secret hook so incident #4 is impossible rather than merely unlikely
2. Decide what past-papers mode should be: honest practice-question generator (rename it) or real paper retrieval (`include_raw_content`, then `.pdf` fetch + `pypdf` extraction). Right now the name promises the second and delivers the first
3. Phase B — session logging, still the bottleneck for the fine-tuning dataset, metering, and auth
4. Server-side session state + prompt caching; `/api/reply` still resends full history every turn
