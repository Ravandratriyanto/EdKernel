# Working notes for Claude

## The project

**EdKernel** — Socratic SAT/A-level AI tutor built for the OpenCV AI Competition 2026.
Submitted grant proposal; competition deadline is end of 2026.
`devlog.md` is the running history (newest entry at the bottom). At the start of a
session read **only the last `## Session` entry** (`grep -n "^## Session" devlog.md`) —
the file is ~80k tokens, never load it whole. Reference sections (archive, test
accounts) sit between sessions and aren't "the last entry".
Older sessions, and the "Features built (as of session N)" history that used to live
here, are in the devlog (see its "Archive — history moved out of CLAUDE.md" section).
The devlog records *claims*: verify against the code before acting on one.

Two front ends over the same `core/` package:
- `app.py` — Flask REST API + `static/index.html` (main product)
- `main.py` — CLI tutor (used for evals and quick testing)

They share `core/llm/`, `core/rag/`, `core/vision/`. Tutor prompts have drifted apart three times — if you touch one, check the other.

## Architecture

```
app.py (Flask + /v1/ Blueprint via api_v1.py, Bearer auth)
  └─ core/
       ├─ tutor.py         – start() / reply() — the Socratic loop
       ├─ check.py         – run() — one-shot answer check
       ├─ questions.py     – PDF → question list (pypdf + fitz/vision fallback)
       ├─ prompts.py       – TUTOR_SYSTEM_PROMPT, HINT_LADDER, CHECK_SIGNAL, strip_signal()
       ├─ notes.py         – notes_from_text() — PDF/YouTube text → Markdown revision notes
       ├─ transcripts.py   – YouTube captions; no-captions fallback via yt-dlp + Whisper + keyframes
       ├─ keyframes.py     – extract_keyframes() — OpenCV scene dedupe, keeps last frame per scene
       ├─ misconceptions.py – misconception-map categories
       ├─ rag/
       │    ├─ ingest.py   – build ChromaDB collections from curricula/
       │    └─ retrieve.py – top-k chunk retrieval
       ├─ vision/          – the OpenCV 5 pipeline
       │    ├─ preprocess.py   – find_page → rectify → deskew → binarise
       │    ├─ segment.py      – ink mask → line boxes → crops
       │    ├─ step_checker.py – check_working() → steps, boxes, error_index
       │    └─ image_handler.py – transcribe() / detect_question() / read_frame() via vision LLM
       ├─ video/           – frame extraction + question_from_video()
       └─ llm/             – provider adapters (Groq, Ollama, OpenAI-compat)
api_v1.py    – stateless /v1/ REST Blueprint (Bearer token, 20 calls/min per key)
users.py     – SQLite auth (scrypt passwords, Google sub, guests) + sessions + api_keys
               + progress + quiz_attempts
gamify.py    – XP / streaks / missions / quests rules (app-layer, not core/)
drive_sync.py – optional Google Drive → curricula/<id>/reference/ adapter
pdftext.py   – PDF text extraction helper
lab_setup.py – lab pre-flight run by start-lab.sh/.bat (keys, lab flags, ADPASS check)
quizbank.py  – per-curriculum quiz banks (curricula/<id>/quizzes.json, keys server-side)
curricula.py – manifest loader   settings.py – feature flags (settings.json)
sessionlog.py – JSONL lesson log  ratelimit.py – login + LLM rate limits
bench/       – COOL Graviton benchmark + architecture diagram generator
evals/       – check eval, hint-ladder eval, regression run
flowcharts.html – mermaid diagrams of every subsystem (keep in step with the code)
static/
  index.html   – student SPA (service tiles, tutor, quiz, flashcards)
  teacher.html – teacher upload + ingest status + topic management
  admin.html   – user management + curriculum management (admin2.html = half-built React rewrite)
  dev.html     – monitoring + pre/post study panel, served at /dev/<DEV_PANEL_KEY> (404 otherwise)
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
- `API_KEY` — LLM provider key (Groq / OpenAI-compat). `ingest.py` also accepts `GROQ_API_KEY`
- `TAVILY_KEY` — past-papers web search. **Bug:** admin auto-research (`app.py`) reads
  `TAVILY_API_KEY` instead, so it never sees the key in `.env`
- `DB_DIR` (default `.logs/`), `CHROMA_DIR` (default `data/chroma/`)
- `DEV_PANEL_KEY` — the secret path segment for `/dev/<key>`
- `ADPASS` — password for the `4dmin` admin login (no stored hash); `ADMIN_PANEL_KEY` — path segment for `/admin2/<key>`. Neither is in `.env.example` yet
- `FLASK_SECRET_KEY` — signs the OAuth state cookie; must match across gunicorn workers
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, optional `GOOGLE_ALLOWED_DOMAIN` — Google sign-in
- `BEHIND_PROXY=1` — only behind the ALB (trusts X-Forwarded-*); `OLLM_HTTPS=1` — only over https
- `DEV_BYPASS_AUTH` — dev-only auth bypass; must never be set on a deployment

## Git

Work on `main` and push there — local `master` was renamed to `main` in session 21 and tracks `origin/main`. (`master` still exists on GitHub but is stale.)
Commit and push **only when asked**. Write devlog entries when asked, matching the existing structure including an honest "Known issues" section.

## How the user likes to work

**Bias toward action, not questions.** When the task is clear, make the reasonable call and do it. Do not pause to ask which approach, which file, or whether to proceed — just go. They will redirect if needed.

**Established split:** Claude does frontend (`static/`) directly; the user types
backend (`core/`, `app.py`, `users.py`) to learn it — give file + exact change + syntax
notes. "Just fix it" / "can u just fix it" overrides this for that task only.

**Ask before writing code they might want to type.** They often want to read every line and type it in — that is how they learn. If they say "let me code it", give the file path + exact change to make, not edits to files. If they say "just do it" or "run it", go ahead.

**Explain unfamiliar Python as you go.** Short, plain explanations of syntax — what `rf"..."` means, why `.b64encode(...).decode()` is two steps. Assume the logic is clear and the syntax is not.

**Plain English everywhere.** Short sentences, everyday words.

## Verifying

**Run the thing before saying it works.** Prompt changes especially — two regressions shipped because a change was checked structurally and never against real model output. A live turn through Groq costs almost nothing.

Report what actually happened, including failures. Do not round a partial result up to "done".

## Current Groq model

`llama-3.3-70b-versatile` was deprecated. Current default: `openai/gpt-oss-120b` (OpenAI-compat endpoint via Groq). Check `https://console.groq.com/docs/models` if hitting model errors — the catalogue changes.

**Vision models.** `qwen/qwen3.8-27b` is now the `GROQ_VISION_MODEL` default in
`image_handler.py`. **`qwen/qwen3.6-27b` was decommissioned by Groq** — do NOT
pass it (it 404s and kills the run on the first vision call). That also means the
old "3.6 spent → fall back to 3.8's own bucket" trick is gone: there is one vision
bucket now, so budget the 200k TPD accordingly. Check
`https://console.groq.com/docs/models` before a run — the catalogue changes.

**Free-tier limits bite hard on vision.** Two separate ceilings:
- **ITPM 7,000** input tokens/minute. One upscaled line crop is ~2,100 tokens,
  so roughly **3 vision calls a minute**. Pace eval runs with `--pause`.
- **TPD 200,000** tokens/day, *per model*. A full 9-case eval run costs a large
  slice of that; two runs exhausted both models in one afternoon. Budget it, or
  the run you care about dies half way.

`qwen3.8` also returns transient **503 "over capacity"** under load, which killed
3-4 cases per run even with backoff. Retries help; luck helps more.

## Current state (as of 2026-10-22 — REWRITE this section each session, keep it short)

Verified against the code on 2026-10-22. History lives in the devlog, not here.

**Deploy:** AWS ECS Fargate + ALB `edkernel-alb-1135643304.ap-southeast-1.elb.amazonaws.com`.
Last recorded redeploy: session 31. Everything since is **not deployed**.

**Lab setup:** `start-lab.sh` / `start-lab.bat` run `lab_setup.py`, which writes
`auth_required: true`, `guest_login: true`, `stub_testing: false` into `settings.json`
(so after a lab run, local login stays ON). Students: guest sign-in at
`http://<LAN IP>:5000`. Admin: log in as `4dmin` (password = `ADPASS` env, **still
empty in `.env`**) at `localhost`, then `/chats` — a dev panel that shows many chats
side by side, live (`static/dev.html` — un-gitignored 2026-10-22, so clones get it).
Only one class is live: `cambridge-as-p1`, named **Math**; the GCSE
classes are in `curricula_archive/`. Lab quiz = 10 MCQs (user's 8 straight-line + 2
circle); the tutor/Questions tab still use the old 5 circle questions. Tutor avatar is
the user's character — smiles when the student is right.

**Auth:** Google sign-in built, never round-tripped (no client ID; needs https or
localhost). Guest mode: same name **resumes** the same account — two students with
one name share it. With auth off, `/chats` + `/api/dev` are open to the network.
`4dmin` can be registered as a student first. API keys minted while auth was off are
still valid.

**Open — security:** `[ANSWER: X]` reaches the browser from `/api/papers` and
`/api/practice_from_error`; no CSRF; curricula have no owner.

**Open — correctness:** `build_tutor_prompt()` in `core/prompts.py` replaces a sentence
the prompt no longer contains, so **every class gets the generic "SAT and A-level"
tutor** (fix given to user, not applied); admin auto-research reads `TAVILY_API_KEY`
(see Env vars); generated MCQs put every answer on A; notes model makes arithmetic
slips; `sessionlog.LOG_DIR` ignores `DB_DIR` (tests write to the real log).

**Open — features:** quiz bank has no editing UI; ingest doesn't run on container
start; Manim renderer; quiz photo grading; `bench/graviton_standalone.py` has a stale
`segment()` — re-sync before quoting COOL numbers.

**Unverified:** `start-lab.bat` on Windows; a full `start-lab.sh` launch; the happy
face after a live Groq `[CORRECT]`; quiz maths + guest button in a real browser;
Bedrock (AWS hold case 178878401900360); the `CHECK_PROMPT` notation fix.

**Top scored work (still not started):** 5-min demo video (required deliverable);
Impact evidence is one 3-student lab (2026-10-23) + informal spoken feedback, no pre-test; confirm the real submission
deadline (unreconciled since session 33).

**Already done — don't re-propose:** HoughLinesP → contour deskew; `dev.html` exists;
emoji → SVG swap; `_fetch_pdf` redirect hole closed; `/api/reply` errors show in the
chat; multi-chat dev panel; lab launchers set the flags.

## Measured numbers (re-run before quoting — stale numbers were corrected 3 times)

Groq `openai/gpt-oss-120b` + `qwen/qwen3.8-27b`, temp 0, nine photos
(`evals/vision_samples/v1–v9`, one student, one pen). "Not obviously broken", not validated.
Last full run 2026-10-23 (session 40), all 9 scored:
- Segmentation line counts **9/9** (pure OpenCV, reproducible). Was silently 8/9
  from 2026-09-17 to 2026-10-23 (v2, margin dash bridging rows) — re-check it.
- Step checker **8/9** — only miss is v1, a misread (`2x+7=19` → `2x+2=10`).
- Transcription **25/30 lines**, 5/9 clean; verdict given a faithful read **5/5**.
- Error located **3/3** (v7–v9).
- Hint ladder **3/5** (`evals/learn_cases.jsonl`, session 28) — two leak the answer early.
- Error-faithfulness thesis tested **flat** (2/3 vs 2/3) — do not pitch it.

## Things that keep biting

- **Don't tune vision thresholds on synthetic images.** `MIN_INK_FRAC` in
  `segment.py` was set to 0.12 from a `cv2.putText` synthetic test (text density
  0.25+), which then dropped **real** handwriting — real pen strokes are only
  ~0.08-0.11 density. It's now **0.03** (0.05 until session 29, lowered when the
  filter moved after the row merge — a merged line box includes the gaps between
  terms, so `x = 6.` in large sparse writing measures well under 0.05). A single
  density threshold can't separate synthetic noise (0.07) from real handwriting
  (0.09); keep it low so real working lines are never dropped. Always validate
  vision changes on a real photo, not just `putText`.
- **Order of operations in `segment()` is load-bearing.** `MIN_BOX_W`,
  `MIN_ASPECT` and `MIN_INK_FRAC` describe a **whole line of working**. The
  horizontal smear only closes gaps up to `kw` px, so one written line arrives
  as several blobs (`4x` and `=20` separately). Running those filters before
  `_merge_rows` deleted the narrow fragment, and the survivor became "the line"
  — `4x = 20` was cropped to `=20` and transcribed as `-20`. Sequence must stay:
  border/speck removal → drop over-tall blobs → **merge** → line-shaped
  thresholds. (Over-tall blobs must go *before* the merge: v4's margin rule
  vertically overlaps every row and collapses the page into one box.)
- **Never size a merge threshold off `min(h, H)`.** `overlap * min(h, H)` lets a
  4px speck set a 2px bar; one merge grows a box, the bigger box reaches the
  next row, and a whole page cascades into a single box. Measure against the
  **median** blob height — a fixed bar can't be dragged down by the smallest
  thing in the set.
- **The edge filter must target frame artifacts, not anything touching the
  edge.** It used to drop every blob reaching the border, which deleted real
  writing whenever a descender hit the last row (v6's `= 5` went, leaving a bare
  `x` that the model read as `\frac{x}{x}`). A real border artifact is long
  **and thin**; require that shape before discarding.
- **Line crops must be upscaled before transcription.** A segmented line off a
  phone photo is only ~27-43px tall — below what a vision model can resolve, and
  no prompt fixes it. `_upscale()` in `step_checker.py` takes them to 96px. Cost:
  ~10× the image area, ~2,100 input tokens per call, which is what makes eval
  runs burn the daily quota.
- **A repeated line is not an error.** Students copy a line out again before
  working on it. The checker called that "no transformation has been performed",
  flagged the copy, and stopped — masking the real mistake further down.
  `_same_line()` decides this without a model call, and has to survive `$x=6$`
  vs `$x = 6$`, `x^2` vs `x^{2}`, and the question number attaching to only the
  first line.
- **Always pass `timeout=` to the Groq SDK.** Its default is 600s with 2 silent
  internal retries — one stuck call hangs for 30 minutes. Both clients now use
  `timeout=60, max_retries=0` so `_with_retry` owns the retry decision.
- **`APIConnectionError` says only `"Connection error."`** — no "429", no "rate
  limit". A `_TRANSIENT` list matching on those strings silently discards
  throttled calls. Groq's 429 body *does* name the wait ("try again in
  15.557142857s"); `_retry_delay()` parses it, because exponential backoff from
  1s never reaches a 15s window.
- **Windows console is cp1252 and model output is not.** Explanations come back
  with U+202F (narrow no-break space); printing one raises `UnicodeEncodeError`
  and killed the eval report *after* a successful run. Any script that prints
  model text needs `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`.
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

**Positioning (judge-facing):** say **"engine"**, not "kernel" (no LTI, no external
adopters). The GCSE tutor is a *distro* of the engine (`core/` + `/v1/`). OpenCV is
deterministic spatial grounding + the COOL benchmark, **not** a recognition-beater —
frontier models read handwriting better. Defensible claims: deterministic grounding
on real paper · evidence-derived misconception map · open/self-hostable.
`~/Desktop/photo-db` (face-recognition gallery) was considered as a pivot and
**rejected** — don't reopen it as the competition entry.
**Pattern to watch:** new features (animations, notes, gamification, admin rewrite)
keep landing while the scored work above sits idle. Say so when it happens.
