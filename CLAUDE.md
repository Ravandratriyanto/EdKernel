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
app.py (Flask, 58 routes + /v1/ Blueprint via api_v1.py, Bearer auth)
  └─ core/
       ├─ tutor.py         – start() / reply() — the Socratic loop
       ├─ check.py         – run() — one-shot answer check
       ├─ questions.py     – PDF → question list (pypdf + fitz/vision fallback)
       ├─ prompts.py       – TUTOR_SYSTEM_PROMPT, HINT_LADDER, CHECK_SIGNAL, strip_signal()
       ├─ rag/
       │    ├─ ingest.py   – build ChromaDB collections from curricula/
       │    └─ retrieve.py – top-k chunk retrieval
       ├─ vision/          – the OpenCV 5 pipeline
       │    ├─ preprocess.py   – find_page → rectify → deskew → binarise
       │    ├─ segment.py      – ink mask → line boxes → crops
       │    ├─ step_checker.py – check_working() → steps, boxes, error_index
       │    └─ image_handler.py – transcribe() / detect_question() via vision LLM
       ├─ video/           – frame extraction + question_from_video()
       └─ llm/             – provider adapters (Groq, Ollama, OpenAI-compat)
api_v1.py    – stateless /v1/ REST Blueprint (Bearer token, 20 calls/min per key)
users.py     – SQLite auth + sessions + api_keys + progress + quiz_attempts
quizbank.py  – per-curriculum quiz banks (curricula/<id>/quizzes.json, keys server-side)
curricula.py – manifest loader   settings.py – feature flags (settings.json)
sessionlog.py – JSONL lesson log  ratelimit.py – login + LLM rate limits
bench/       – COOL Graviton benchmark + architecture diagram generator
evals/       – check eval, hint-ladder eval, regression run
flowcharts.html – mermaid diagrams of every subsystem (keep in step with the code)
static/
  index.html   – student SPA (service tiles, tutor, quiz, flashcards)
  teacher.html – teacher upload + ingest status + topic management
  admin.html   – user management + curriculum management
```

**Key invariants:**
- `core/` is pure Python — no Flask, no SQLite, no HTTP imports
- `_SIGNAL_RE` anchored to end-of-string — `[CORRECT]`/`[WRONG]` must be last in any tutor reply
- `drop_reasoning()` strips `<think>` blocks from reasoning models before any processing
- Quiz answer keys never leave the server before submission — questions go out
  through `_public_questions()`, marking happens in `/api/quiz/submit`

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

Work on `main` and push there — local `master` was renamed to `main` in session 21 and tracks `origin/main`. (`master` still exists on GitHub but is stale.)
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

## Features built (as of session 27)

- **Server-marked quizzes (`quiz_attempts` table)**: `POST /api/quiz/start`
  opens an attempt holding the questions *with* their keys and returns them
  key-stripped. `POST /api/quiz/submit` compares each letter against the stored
  row, records progress for **right and wrong**, and returns the review with the
  keys and worked solutions. `POST /api/quiz/answer` marks a single question
  (in-chat papers flow); `POST /api/quiz/tab-switch` persists the counter;
  `GET /api/teacher/curricula/<cid>/attempts` feeds the dashboard. Attempts are
  scoped by user id, so one student cannot touch another's. Marking is once per
  question — a resubmit re-renders the review and writes nothing.
  Replaces `/api/papers/correct`, which took mastery on the client's word.
- **Quiz bank server-side**: `quizbank.py` reads `curricula/<id>/quizzes.json`.
  `PREMADE_QUIZZES` is gone from `index.html` — its keys were visible in
  devtools, and all five answers were `A`.
- **Dev flags are admin-only**: `/dev`, `GET` and `PUT /api/dev/settings` left
  `_OPEN_ENDPOINTS`. Anyone who could reach the app could previously
  `PUT {"auth_required": false}` and be served as admin.
- **`/v1/` rate limited and actually reachable**: 20 calls/min per key owner,
  enforced inside `require_auth` so no new route can skip it. Separately,
  `_load_user` now lets `request.blueprint == "v1"` past the cookie gate — every
  Bearer caller used to 401 before the blueprint ran, so the API was dead
  whenever `auth_required` was true.
- **Flowcharts current**: `flowcharts.html` has 21 diagrams including the
  OpenCV 5 pipeline, the quiz attempt flow, progress, and AWS deployment.
- **Annotated vision output** (from the parallel machine's branch): `check_working()`
  returns `annotated` — a base64 JPEG of the cleaned page with each line boxed
  (error red, others green, numbered) via `_annotate()` in `step_checker.py`.
  Frontend shows it directly; drawing on the preprocessed image means boxes line
  up even after warp/deskew (old client-side overlay kept as fallback).
- **Error-triggered practice**: when the step checker finds an error, a
  "Practice this mistake" button calls `POST /api/practice_from_error`
  (`PRACTICE_FROM_ERROR_PROMPT`, reuses `_parse_questions`/`_format_questions`),
  loading MCQs into the inline papers flow. Closes the vision → tutor →
  curriculum loop. Needs a reachable LLM.
- **Vision eval harness**: `evals/vision.py` + `evals/vision_cases.jsonl`. Metric
  is exact match on `error_index`. **No sample photos yet** — no accuracy number
  until `evals/vision_samples/` is populated.

## Features built (as of session 26)

- **Gojek-style student home**: after picking a class the student sees a
  service-tile grid (Learn / Papers / Upload / Quiz), not the tutor directly.
  `enterService(type)` dispatches; `showChatView()`/`backToCanvas()` restore
  `#main-col` and stop the quiz watcher so no view stays stuck hidden.
- **Quiz mode (SAT Bluebook style)**: two-pane layout (problem left, choices
  right), count-up timer, A/B/C/D circles, "Question X of Y" + Next/Finish.
  **No live right/wrong** — selecting only records the choice (teacher feedback:
  live marking spikes exam nerves). On Finish, `finishQuiz()` shows score, time,
  tab-switch count, and a per-question review with worked solutions.
  `analyzeQuiz()` sends the attempt to `/api/start` for encouraging AI feedback
  (degrades gracefully with no LLM). `PREMADE_QUIZZES` holds a static GCSE Maths
  set (instant, no LLM); other classes fall back to RAG via `/api/papers`.
  Tab-switch detection uses `visibilitychange` only (not `window blur`, which
  false-fired on DevTools/focus changes).
- **COOL benchmark**: `bench/graviton_bench.py` + dependency-free
  `bench/graviton_standalone.py` time the OpenCV pipeline ops. Ran on t4g.micro
  (aarch64) vs local x86. Results in `bench/results/{x86,graviton}.json`.
  HoughLinesP is the bottleneck on both (6.6× worse on Graviton); Graviton wins
  findContours + ink_mask. Not clean apples-to-apples (OpenCV 4.5 vs 5.0).
- **Technical report + diagram**: `report.md` (full competition report) and
  `docs/architecture.png` (generated by `bench/make_diagram.py`).

## Features built (as of session 25)

- **OpenCV 5 pipeline**: rectify → binarise → segment → transcribe → evaluate. Bounding boxes returned to front end and drawn on canvas overlay (green = correct, red = error line).
- **Step checker inline**: no longer a separate mode — fires automatically when a student attaches an image in Learn mode. `runStepChecker(attach)` called after the tutor bubble renders; bounding-box canvas appears if steps are found; silent if not.
- **Maths PDF vision path**: `fitz` converts PDF pages to JPEG at 150 DPI; vision LLM transcribes. Auto-fallback triggers when pypdf returns <100 chars OR `_junk_ratio()` > threshold.
- **Auto-reingest**: uploading a new paper or curriculum triggers background ingest. `_INGEST_STATUS` dict tracks per-curriculum state. Admin and teacher panels poll `GET /api/admin/ingest/<cid>` for live status. **Caveat**: Gunicorn multi-worker means GET may hit a different worker than POST — dict state unreliable; verify by testing the endpoint, not the status.
- **Progress tracking**: SQLite `progress` table `(user_id, curriculum, topic_id, attempts, correct, last_seen)`. Mastery = correct/attempts: ≥0.8 green dot, >0 yellow, untouched grey. Student sees dots on topic list; "Continue" banner shows recommended next topic.
- **Hint ladder**: 4-rung escalation. Rung 1 = no mathematical vocabulary, rung 2 = name the concept, rung 3 = explain + apply. **Real score: 3/5** on `evals/learn_cases.jsonl` (deterministic, `temperature=0`, groq `openai/gpt-oss-120b`, session 28). The two failures leak the answer before the final rung (photosynthesis → "chloroplast" at rung 2; percentage → "25%" before rung 3). The old "10/10" claim here was wrong; the proposal's "1/5" is stale. Do not quote a number without re-running.
- **URL routing**: `openClass()` calls `history.pushState({cid}, '', '/?c=<id>')`. Back button returns to class list. Direct URL `/?c=<id>` auto-opens curriculum after login.
- **AWS ECS Fargate**: Docker → ECR → ECS Fargate + ALB. Stable URL: `edkernel-alb-1135643304.ap-southeast-1.elb.amazonaws.com`. EFS mounted at `/app/.logs` and `/app/data/chroma` for SQLite + ChromaDB persistence across task replacements. Current task definition: revision 14.
- **GCSE Mathematics curriculum (PMT)**: 88 revision note PDFs from Physics and Maths Tutor ingested into `gcse_maths` ChromaDB collection (951 chunks). Covers Number, Algebra, Ratio/Proportion, Geometry, Probability, Statistics. PDFs live in `curricula/gcse-maths/reference/` (baked into image via `.dockerignore` rules).
- **RAG-based MCQ generation**: `/api/papers` falls back to `retrieve(topic, n_results=10, collection_name=collection)` when `TAVILY_API_KEY` is absent. Generates A/B/C/D MCQs from curriculum chunks. Verification (`_verify_questions`) filters with unverified fallback if verifier rejects all.
- **Flashcard system**: Questions tab has Browse/Flashcards toggle. Flashcards mode: flip animation (CSS 3D), No idea/Nearly/Got it rating buttons, end screen with score. Spaced repetition via `localStorage` — weak cards surface first next session.
- **Auth disabled for dev**: `settings.json` with `auth_required: false` bypasses all login. `#auth-gate` starts hidden; no env var needed. Network access on `0.0.0.0:5000` — accessible at `192.168.100.30:5000`.

## Pending (as of session 27)

- **AWS Bedrock provider** in `core/llm/client.py` — blocked on account
  verification hold (`ValidationException: Operation not allowed`, case
  178878401900360). Fargate hold cleared session 26; Bedrock still open.
- **Quiz bank has no editing UI** — `curricula/<cid>/quizzes.json` is read by
  `quizbank.py` and only `gcse-maths` has one. Teachers cannot add or generate
  quiz questions from the panel yet; the file has to be edited by hand.
- **The in-chat papers flow still ships answer keys to the browser.** Marking
  goes through `/api/quiz/answer` now, so progress is server-derived, but
  `/api/papers` still returns `[ANSWER: X]` in its wire format, so a student
  reading the network tab can see the key. Quiz mode does not.
- **Replace HoughLinesP deskew** with a contour-based rotation estimate (COOL
  benchmark showed it is the pipeline bottleneck, 6.6× worse on Graviton).
- **Quiz upload grading** — `handleQuizImage()` OCRs the photo but does not
  grade a handwritten/doodled answer against the key.
- **Live bounding boxes** in step checker UI (backend returns boxes; frontend does not draw overlay on the canvas)
- **Tavily web search fallback** — knowledge-cutoff guardrail is currently a prompt workaround; Tavily key is already in env
- **Manim video renderer** — LLM writes Manim Python → renders MP4 → served in chat
- **5-minute demo video** (required for competition submission)
- **Ingest auto-trigger on container start** — currently must be re-run manually after each ECS task replacement
- Frontend error toast for `/api/reply` 500s (spinner hangs silently on model error)
- **`_fetch_pdf` follows redirects** — `_allowed_paper_host()` only checks the
  original URL, so an allowlisted domain can redirect the server anywhere. Blind
  (the body must start with `%PDF`), but `allow_redirects=False` is a one-liner.
- **No CSRF token** on cookie-authenticated state-changing routes; `samesite="Lax"`
  is partial cover only.
- **Curricula have no owner** — `/api/teacher/...` is role-gated but any teacher
  can edit any curriculum. A data-model decision, not a missing check.
- **`/dev` serves `static/dev.html`, which does not exist** — the route 404s (admin-only since session 27); the flags it edits still work through `settings.json` directly

## Things that keep biting

- **Don't tune vision thresholds on synthetic images.** `MIN_INK_FRAC` in
  `segment.py` was set to 0.12 from a `cv2.putText` synthetic test (text density
  0.25+), which then dropped **real** handwriting — real pen strokes are only
  ~0.08-0.11 density. It's now 0.05. A single density threshold can't separate
  synthetic noise (0.07) from real handwriting (0.09); keep it low so real
  working lines are never dropped. Always validate vision changes on a real
  photo, not just `putText`.
- **Pin `temperature=0` on the vision call too.** `_groq_vision` was
  non-deterministic — the same image read cleanly one run and fragmented the
  next, poisoning the step check. All LLM calls (chat AND vision) now pin temp 0.
- Real cluttered/angled photos: `find_page` returns None (no clean page quad),
  so `preprocess` only deskews and keyboard/desk clutter stays in frame. The
  step-checker is sound on flat single-problem shots; robustness on real messy
  pages needs page isolation + problem grouping (not yet built).
- The answer key must never reach the browser before an attempt is submitted.
  Quiz questions go out through `_public_questions()`, which strips `answer` and
  `working`; correctness is decided in `/api/quiz/submit` by comparing against
  the `quiz_attempts` row. Anything that sends a key down to the client puts
  progress back under the student's control.
- `users.create_user()` promotes the **first account in the database to admin**
  regardless of the role argument. Test fixtures that create a "student" first
  get an admin and silently pass role checks.
- `@app.errorhandler(Exception)` used to swallow `HTTPException`, so every 404
  came back as a 500 "Something went wrong on our end". It now re-raises HTTP
  errors with their real status — do not remove that branch.
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
- LaTeX in dynamically-created MCQ option buttons requires `btn.innerHTML` (not `textContent`) plus `renderMathInElement(optRow, {...})` called after all buttons are appended. Store the letter in `btn.dataset.letter` — KaTeX rewrites `textContent`, so reading `textContent[0]` breaks after rendering. The quiz uses `renderQuizMath(el, text)` which wraps `normaliseMath` → `renderMathInElement` → `restoreDollars` for this.
- `crypto.randomUUID` must be called as `crypto.randomUUID()`, not stored/invoked detached. `(crypto.randomUUID ?? fallback)()` throws "Illegal invocation" (loses its `this`) and white-screens the app. Use `crypto.randomUUID ? crypto.randomUUID() : fallback`.
- Tab-switch anti-cheat: use the `visibilitychange` event (checks `document.hidden`), NOT `window` `blur`. `blur` false-fires when the user clicks DevTools or the window merely loses focus.
- Docker `--no-cache` builds via the background-task runner sometimes produced the same image digest (cached layers / wrong context). Verify the built image actually contains an edit with `docker run --rm <img> grep ... /app/static/index.html` before pushing, and build with an explicit context path.

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
