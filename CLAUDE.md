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

**Ask before writing code they might want to type.** They often want to read every line and type it in — that is how they learn. If they say "let me code it", give design + code to work from, not edits to files. If they say "just do it", go ahead.

**Explain unfamiliar Python as you go.** Short, plain explanations of syntax — what `rf"..."` means, why `.b64encode(...).decode()` is two steps. Assume the logic is clear and the syntax is not.

**Plain English everywhere.** Short sentences, everyday words.

## Verifying

**Run the thing before saying it works.** Prompt changes especially — two regressions shipped because a change was checked structurally and never against real model output. A live turn through Groq costs almost nothing.

Report what actually happened, including failures. Do not round a partial result up to "done".

## Current Groq model

`llama-3.3-70b-versatile` was deprecated. Current default: `openai/gpt-oss-120b` (OpenAI-compat endpoint via Groq). Check `https://console.groq.com/docs/models` if hitting model errors — the catalogue changes.

## Features built (as of session 17b)

- **OpenCV 5 pipeline**: rectify → binarise → segment → transcribe → evaluate. Bounding boxes returned to front end and drawn on canvas overlay (green = correct, red = error line).
- **Maths PDF vision path**: `fitz` converts PDF pages to JPEG at 150 DPI; vision LLM transcribes. Auto-fallback triggers when pypdf returns <100 chars OR `_junk_ratio()` > threshold.
- **Auto-reingest**: uploading a new paper or curriculum triggers background ingest. `_INGEST_STATUS` dict tracks per-curriculum state. Admin and teacher panels poll `GET /api/admin/ingest/<cid>` for live status.
- **Progress tracking**: SQLite `progress` table `(user_id, curriculum, topic_id, attempts, correct, last_seen)`. Mastery = correct/attempts: ≥0.8 green dot, >0 yellow, untouched grey. Student sees dots on topic list; "Continue" banner shows recommended next topic.
- **Hint ladder**: 4-rung escalation. Evaluated at 10/10 on `evals/learn_cases.jsonl`. Rung 1 = no mathematical vocabulary, rung 2 = name the concept, rung 3 = explain + apply.
- **URL routing**: `openClass()` calls `history.pushState({cid}, '', '/?c=<id>')`. Back button returns to class list. Direct URL `/?c=<id>` auto-opens curriculum after login.
- **Docker**: `Dockerfile` uses `python:3.12-slim`, gunicorn, `ENV DB_DIR=/app/.logs`, `ENV CHROMA_DIR=/app/data/chroma`, `VOLUME /app/.logs`. Build: `docker build -t edkernel .`

## Pending (as of session 17b)

- Push to AWS ECR → ECS Fargate + ALB
- EFS mount for `/app/.logs` and `/app/data/chroma` (SQLite + ChromaDB persistence)
- Teacher progress UI (`GET /api/teacher/curricula/<cid>/progress` route exists, no HTML yet)
- Graviton EC2 benchmark (COOL Award — $1,000 prize)
- 5-minute demo video (required for competition submission)
- Technical report (required for competition submission)

## Things that keep biting

- `pypdf` loses parentheses and ligatures — `g(x)` can extract as `gx^h`. Always use vision fallback for maths-heavy PDFs.
- `_SIGNAL_RE` is anchored to end-of-string — `[CORRECT]`/`[WRONG]` must be the absolute last thing in a tutor reply.
- Stray SQL at the bottom of `users.py` has appeared three times — someone pasted raw SQL outside any function. Always check the file ends cleanly.
- The default Groq vision model reasons out loud; `<think>` blocks must be stripped before any downstream use.
- Past-paper answer keys were wrong 2-in-3 before the verification pass existed. Never trust a generated key without checking.
- `docker build -t edkernel` without the trailing `.` gives "requires 1 argument" — always add the build context path.

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
