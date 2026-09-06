# Working notes for Claude

## The project

**EdKernel** — Socratic SAT/A-level AI tutor built for the OpenCV AI Competition 2026.
Submitted grant proposal; competition deadline is end of 2026.
`devlog.md` is the running history (newest entry at the bottom). Read it at the start of each session.

Two front ends over the same `core/` package:
- `app.py` — Flask REST API + `static/index.html` (main product)
- `main.py` — CLI tutor (used for evals and quick testing)

They share `core/llm/`, `core/rag/`, `core/vision/`. Tutor prompts have drifted apart three times — if you touch one, check the other.

## Architecture

```
app.py (Flask, /v1/ Blueprint, Bearer auth)
  └─ core/
       ├─ questions.py     – PDF → question list (pypdf + fitz/vision fallback)
       ├─ prompts.py       – TUTOR_SYSTEM_PROMPT, HINT_LADDER, CHECK_SIGNAL, strip_signal()
       ├─ rag/
       │    ├─ ingest.py   – build ChromaDB collections from curricula/
       │    └─ retrieve.py – top-k chunk retrieval
       ├─ vision/
       │    └─ image_handler.py – base64 image → transcription via vision LLM
       └─ llm/             – provider adapters (Groq, Ollama, OpenAI-compat)
users.py     – SQLite auth + sessions + api_keys + progress tables
static/
  index.html   – student SPA
  teacher.html – teacher upload + ingest status + topic management
  admin.html   – user management + curriculum management
```

**Key invariants:**
- `core/` is pure Python — no Flask, no SQLite, no HTTP imports
- `_SIGNAL_RE` anchored to end-of-string — `[CORRECT]`/`[WRONG]` must be last in any tutor reply
- `drop_reasoning()` strips `<think>` blocks from reasoning models before any processing

## Environment / secrets

Keys live in `.env` only. It is gitignored; `.env.example` is the committed template and **must stay blank**. Three keys have leaked into tracked files in the past — treat any key that touches a tracked file as burned and say it needs rotating.

`hooks/pre-commit` blocks commits containing key patterns. A fresh clone needs:
```
git config core.hooksPath hooks
```

**Env vars the app reads:**
- `DB_DIR` — where `users.db` lives (default: `.logs/` next to `users.py`)
- `CHROMA_DIR` — where ChromaDB lives (default: `data/chroma/`)
- `GROQ_API_KEY`, `OPENAI_API_KEY`, `TAVILY_API_KEY`

## Git

Work on `master` and push there — that is the branch this repo uses (`main` exists on GitHub but `master` is the working branch).
Commit and push **only when asked**. Write devlog entries when asked, matching the existing structure including an honest "Known issues" section.

## How the user likes to work

**Bias toward action, not questions.** When the task is clear, make the reasonable call and do it. Do not pause to ask which approach, which file, or whether to proceed — just go. They will redirect if needed.

**Ask before writing code they might want to type.** They often want to read every line and type it in — that is how they learn. If they say "let me code it", give the file path + exact change to make, not edits to files. If they say "just do it" or "run it", go ahead.

**Explain unfamiliar Python as you go.** Short, plain explanations of syntax — what `rf"..."` means, why `.b64encode(...).decode()` is two steps. Assume the logic is clear and the syntax is not.

**Plain English everywhere.** Short sentences, everyday words.

## Verifying

**Run the thing before saying it works.** Prompt changes especially — two regressions shipped because a change was checked structurally and never against real model output. A live turn through Groq costs almost nothing.

Report what actually happened, including failures. Do not round a partial result up to "done".

## Current Groq model

`llama-3.3-70b-versatile` was deprecated. Current default: `openai/gpt-oss-120b` (OpenAI-compat endpoint via Groq). Check `https://console.groq.com/docs/models` if hitting model errors — the catalogue changes.

## Features built (as of session 25)

- **OpenCV 5 pipeline**: rectify → binarise → segment → transcribe → evaluate. Bounding boxes returned to front end and drawn on canvas overlay (green = correct, red = error line).
- **Step checker inline**: no longer a separate mode — fires automatically when a student attaches an image in Learn mode. `runStepChecker(attach)` called after the tutor bubble renders; bounding-box canvas appears if steps are found; silent if not.
- **Maths PDF vision path**: `fitz` converts PDF pages to JPEG at 150 DPI; vision LLM transcribes. Auto-fallback triggers when pypdf returns <100 chars OR `_junk_ratio()` > threshold.
- **Auto-reingest**: uploading a new paper or curriculum triggers background ingest. `_INGEST_STATUS` dict tracks per-curriculum state. Admin and teacher panels poll `GET /api/admin/ingest/<cid>` for live status. **Caveat**: Gunicorn multi-worker means GET may hit a different worker than POST — dict state unreliable; verify by testing the endpoint, not the status.
- **Progress tracking**: SQLite `progress` table `(user_id, curriculum, topic_id, attempts, correct, last_seen)`. Mastery = correct/attempts: ≥0.8 green dot, >0 yellow, untouched grey. Student sees dots on topic list; "Continue" banner shows recommended next topic.
- **Hint ladder**: 4-rung escalation. Evaluated at 10/10 on `evals/learn_cases.jsonl`. Rung 1 = no mathematical vocabulary, rung 2 = name the concept, rung 3 = explain + apply.
- **URL routing**: `openClass()` calls `history.pushState({cid}, '', '/?c=<id>')`. Back button returns to class list. Direct URL `/?c=<id>` auto-opens curriculum after login.
- **AWS ECS Fargate**: Docker → ECR → ECS Fargate + ALB. Stable URL: `edkernel-alb-1135643304.ap-southeast-1.elb.amazonaws.com`. EFS mounted at `/app/.logs` and `/app/data/chroma` for SQLite + ChromaDB persistence across task replacements. Current task definition: revision 14.
- **GCSE Mathematics curriculum (PMT)**: 88 revision note PDFs from Physics and Maths Tutor ingested into `gcse_maths` ChromaDB collection (951 chunks). Covers Number, Algebra, Ratio/Proportion, Geometry, Probability, Statistics. PDFs live in `curricula/gcse-maths/reference/` (baked into image via `.dockerignore` rules).
- **RAG-based MCQ generation**: `/api/papers` falls back to `retrieve(topic, n_results=10, collection_name=collection)` when `TAVILY_API_KEY` is absent. Generates A/B/C/D MCQs from curriculum chunks. Verification (`_verify_questions`) filters with unverified fallback if verifier rejects all.
- **Flashcard system**: Questions tab has Browse/Flashcards toggle. Flashcards mode: flip animation (CSS 3D), No idea/Nearly/Got it rating buttons, end screen with score. Spaced repetition via `localStorage` — weak cards surface first next session.
- **Auth disabled for dev**: `settings.json` with `auth_required: false` bypasses all login. `#auth-gate` starts hidden; no env var needed. Network access on `0.0.0.0:5000` — accessible at `192.168.100.30:5000`.

## Pending (as of session 25)

- **AWS Bedrock provider** in `core/llm/client.py` (competition AWS requirement — meaningful AWS AI usage)
- **Teacher progress UI** (`GET /api/teacher/curricula/<cid>/progress` route exists, no HTML yet)
- **Graviton EC2 benchmark** (COOL Award — $1,000 prize)
- **Fix `index.html` title** from "OLLM Tutor" to "EdKernel"
- **Live bounding boxes** in step checker UI (backend returns boxes; frontend does not draw overlay on the canvas)
- **Tavily web search fallback** — knowledge-cutoff guardrail is currently a prompt workaround; Tavily key is already in env
- **Manim video renderer** — LLM writes Manim Python → renders MP4 → served in chat
- **5-minute demo video** (required for competition submission)
- **Technical report** (required for competition submission)
- **Ingest auto-trigger on container start** — currently must be re-run manually after each ECS task replacement
- Frontend error toast for `/api/reply` 500s (spinner hangs silently on model error)

## Things that keep biting

- `pypdf` loses parentheses and ligatures — `g(x)` can extract as `gx^h`. Always use vision fallback for maths-heavy PDFs.
- `_SIGNAL_RE` is anchored to end-of-string — `[CORRECT]`/`[WRONG]` must be the absolute last thing in a tutor reply.
- Stray SQL at the bottom of `users.py` has appeared three times — someone pasted raw SQL outside any function. Always check the file ends cleanly.
- The default Groq vision model reasons out loud; `<think>` blocks must be stripped before any downstream use.
- Past-paper answer keys were wrong 2-in-3 before the verification pass existed. Never trust a generated key without checking.
- `docker build -t edkernel` without the trailing `.` gives "requires 1 argument" — always add the build context path.
- `normaliseMath(undefined)` crashes with "Cannot read properties of undefined (reading 'split')". Guard: `if (!text) return '';`. Also check `data.error` before passing `data.response` to `appendBubble` — server errors return `{"error": "..."}` with no `response` field.
- `_verify_math` and `_ai_evaluate` are defined in `app.py` but intentionally not called — they caused correlated failures (same model verified its own wrong answer) and added 3–9 s latency. Do not re-enable without switching to a separate verification model.
- Patching `TUTOR_SYSTEM_PROMPT` incrementally creates contradictions fast. The prompt was rewritten clean in session 19. If adding new rules, check for contradictions with the four labelled sections before committing.
- Browser caches `index.html` aggressively. The `/` route now sets `Cache-Control: no-store`. A stale cached page on another device shows the old UI; fix with hard refresh (`Ctrl+Shift+R`).
- PMT revision PDFs are diagram-heavy and often scan-based. pypdf extracts garbled text from them, producing low-quality RAG chunks. Generated MCQ answer keys can be wrong even when the question looks plausible. Vision transcription of PDF pages would improve this, but is not implemented for the ingestion path.
- Gunicorn multi-worker means `_INGEST_STATUS` (in-process dict) is unreliable as a status indicator: a GET may hit a different worker than the POST that started ingest. The EFS writes still succeed. Never trust the status endpoint alone — verify by hitting the feature directly.
- LaTeX in dynamically-created MCQ option buttons requires `btn.innerHTML` (not `textContent`) plus `renderMathInElement(optRow, {...})` called after all buttons are appended. Store the letter in `btn.dataset.letter` — KaTeX rewrites `textContent`, so reading `textContent[0]` breaks after rendering.

## Competition context

**OpenCV AI Competition 2026** — judging weights:
- OpenCV 5 depth (30%) — pipeline must genuinely use OpenCV 5 APIs
- Innovation (20%)
- Impact (20%)
- UX/Design (10%)
- Documentation (10%)
- AWS integration (10%)

**Special awards:**
- COOL Award ($1,000): Graviton EC2 benchmark showing ARM advantage
- Agentic Vision Award: perception → decision → action loop (our pipeline qualifies)

Architecture gap to fix before final submission: EdKernel is a monolithic Flask app, not an LTI-compatible "kernel". The grant proposal calls it a kernel — avoid repeating that framing to judges without explaining it.
