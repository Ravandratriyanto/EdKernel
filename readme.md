# EdKernel

A curriculum-agnostic AI tutoring engine and LMS kernel. Drop in a curriculum
directory and get a Socratic tutor, a per-step handwritten-math checker, a
past-paper question importer, and a stateless REST API — all over the same
core with no dependency on any specific LMS.

---

## What it does

- **Socratic tutor** — teaches one concept at a time, asks questions instead
  of lecturing, escalates hints based on wrong-answer streak
- **Answer checker** — explains why an answer is right or wrong, with
  reference material grounding from ChromaDB RAG
- **Handwritten step checker** — OpenCV segments each line of working,
  transcribes it with a vision model, and finds the first wrong step
- **Past paper import** — fetches a PDF from an allowed revision site,
  extracts and lightly paraphrases questions, appends to the question bank
- **Stateless REST API** (`/v1/`) — Bearer-token auth, no cookies, callable
  by any external LMS without touching the login system or UI

---

## Architecture

```
EdKernel/
  core/                        Pure Python AI engine — no Flask, no SQLite
    llm/client.py              generate() + chat() — Ollama and Groq
    prompts.py                 All shared prompt text + [CORRECT]/[WRONG] parser
    rag/
      ingest.py                Build ChromaDB collection from reference PDFs + notes
      retrieve.py              Vector search — per-curriculum collection
    vision/
      image_handler.py         Image → text (transcribe, drop_reasoning)
      step_checker.py          OpenCV segment + transcribe each line of working
      preprocess.py            Binarise + rectify image before segmentation
      segment.py               Horizontal line segmentation
    video/
      frame_extractor.py       Extract key frames from video (ffmpeg)
      video_handler.py         Deduplicate + merge frame transcriptions
    check.py                   run(question, answer, context) → feedback + verdict
    tutor.py                   start() / reply() — stateless Socratic session
    questions.py               extract_from_paper(pdf_bytes) → question list

  app.py                       Flask server — 48 routes, 3 browser UIs
  api_v1.py                    Blueprint at /v1/ — stateless REST, Bearer auth
  main.py                      CLI — check and learn modes
  users.py                     Accounts (scrypt), sessions, API keys (SHA-256)
  curricula.py                 Curriculum manifest loader
  settings.py                  Runtime feature flags (settings.json)
  sessionlog.py                Append-only lesson log → .logs/sessions.jsonl
  ratelimit.py                 Sliding-window login throttle

  curricula/<id>/
    manifest.json              name, prompt_flavour, collection, subjects
    topics.json                Topic tree with subtopics and objectives
    questions.json             Question bank (text, answer, marks, image)
    reference/                 .txt notes, spec PDFs — ingested into ChromaDB
    papers/                    Past paper PDFs — ingested into ChromaDB

  static/
    index.html                 Student UI — 3-view: classes, topics, tutor
    teacher.html               Teacher UI — topics, question bank, materials
    admin.html                 Admin UI — curricula, users, API keys

  evals/
    run.py                     Score check mode — 50 cases, sympy-verified keys
    learn.py                   Score hint ladder — 5 cases, 3 rungs each
    regress.py                 Fast regression checks — no model calls
```

---

## Providers

| Provider | Text models | Vision models |
|---|---|---|
| Ollama (local) | any model pulled locally | any multimodal model |
| Groq (cloud) | `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` | `qwen/qwen3.6-27b` |

Keys live in `.env` only — see `.env.example`. The app reads `API_KEY`
(Groq) and `TAVILY_KEY`. Both are passed per-request from the UI or
defaulted from the environment.

---

## Running it

```bash
# one-time setup
pip install -r requirements.txt
git config core.hooksPath hooks          # enables the pre-commit key check

# build the RAG collection for a curriculum
python -m core.rag.ingest --curriculum sat-alevel

# start the server
python app.py                            # http://localhost:5000

# or the CLI
python main.py check --text "What is 2x if x=3?" --answer "6" --provider groq
python main.py learn --text "Explain supply and demand" --provider groq
```

First account registered becomes admin automatically.

---

## /v1/ API

Stateless REST — no cookies. Auth via `Authorization: Bearer <token>`.
Create a token in the admin panel (Admin → API keys).

```
GET  /v1/ping                            health check, no auth
POST /v1/check                           {question, answer, context?} → {feedback, correct}
POST /v1/tutor/start                     {topic, context?, question_bank?} → {reply, correct, messages}
POST /v1/tutor/reply                     {messages, message, wrong_streak?} → {reply, correct, messages}
POST /v1/questions/extract               multipart: file (PDF) → {questions, count}
POST /v1/check-working                   multipart: file (image) → {steps, boxes, error_index, explanation}
GET  /v1/keys                            list your API keys
POST /v1/keys                            {label} → {token}  — shown once
DELETE /v1/keys/<id>                     revoke a key
```

Callers own the full `messages` array — pass it back on every `/v1/tutor/reply`
call (OpenAI pattern). The server holds no session state.

---

## Evals

```bash
python -m evals.run                      # check mode — 50 cases
python -m evals.run --only regress       # regressions only — no model calls, ~7s
python -m evals.learn                    # hint ladder — 5 cases, 3 rungs
```

**Current scores (Groq `openai/gpt-oss-120b` / `qwen/qwen3.6-27b`):**
- Check mode: 50/50 — 0 unparsed, 0 errors
- Regressions: 39/39
- Hint ladder: 2/5 — rung 2 naming is the open failure

The score moves ~2 points between identical runs (temperature not pinned).
Treat anything under 3 points as noise and run twice. One full check-mode
run costs ~¼ of Groq's free daily token budget.

**`qwen/qwen3.6-27b` is a reasoning model** — it outputs `<think>` blocks.
Only use it on the vision path (where `drop_reasoning()` is called) or the
learn eval (which now strips think blocks before checking). Do not use it
for check mode — `<think>` blocks would reach the student.

---

## Curricula

Each curriculum is a directory under `curricula/`. The manifest drives
everything — prompt flavour, ChromaDB collection name, subjects.

```bash
# after dropping PDFs into curricula/sat-alevel/reference/ or papers/
python -m core.rag.ingest --curriculum sat-alevel
```

The admin panel creates new curricula, edits topic trees, manages the
question bank, and triggers re-ingestion without touching the filesystem.

---

## Known issues and open work

- **Hint ladder rung 2** — eval scores 2/5. Rung 2 should name the concept
  explicitly; current prompt is too subtle on some cases.
- **Phase B token counts on Ollama** — session log token counts have only
  been verified on Groq. Ollama counts are read from `prompt_eval_count` /
  `eval_count` and warned if zero, but never measured end-to-end in a real
  lesson.
- **Phase C (LoRA fine-tune)** — needs enough logged sessions first.
- **maths past papers** — pypdf corrupts equations. The vision pipeline
  (OpenCV + vision model) is the fix; not yet wired into question import.
- **Progress tracking** — the kernel knows what topics exist but has no
  per-student mastery state. Per-topic completion is the next meaningful
  LMS feature.

---

## Phase log

- [x] Phase 1 — model connection (Ollama + Groq)
- [x] Phase 2 — CLI check + learn mode
- [x] Phase 3 — RAG grounding (ChromaDB, per-curriculum collections)
- [x] Phase 4 — Socratic learn mode loop
- [x] Phase 5 — Escalating hint ladder
- [x] Phase 6 — Image input (vision transcription, Ollama + Groq)
- [x] Phase 7 — Video input (ffmpeg frame extraction + merge)
- [x] Phase A — Transformer from scratch (`training/train_tiny.py`)
- [ ] Phase B — Session logging complete (token counts on Ollama unverified)
- [ ] Phase C — LoRA fine-tune on logged sessions
