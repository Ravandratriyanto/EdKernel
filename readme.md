# SAT/A-level LLM Tutor — Build Plan

This is a spec to build against, not a copy of finished code. Each section
describes what a piece needs to *do* — you write the actual implementation.

## What this project is

An LLM-based tutor that takes a question (typed, photographed, or from
video) and either:
- **learn mode** — teaches it step by step, correcting you as you go
- **check mode** — just tells you if your answer is right

Built on Ollama (local/remote model serving) + ChromaDB (RAG grounding
against real syllabus/past-paper material), all orchestrated in Python.

## Architecture

```
sat_tutor/
  llm/client.py          Talks to Ollama: send a prompt, get text back
  rag/ingest.py           Load reference material into ChromaDB
  rag/retrieve.py         Pull relevant reference chunks for a question
  core/decompose.py       Break a question into ordered teaching steps
  core/hints.py           Generate a hint that escalates with each wrong attempt
  core/session.py         Track where a student is in a learn-mode session
  core/checker.py         One-shot answer verification
  core/modes.py           Decide: learn or check, and call the right thing
  vision/image_handler.py Turn a photographed question into text
  video/frame_extractor.py  Pull frames (and audio) out of a video file
  video/video_handler.py    Turn a video question into text
  prompts.py               Shared prompt text + the [CORRECT]/[WRONG] parser
  evals/run.py             Score check mode against questions with known answers
  evals/regress.py         Fast checks for bugs already fixed once
  main.py                  CLI: parse args, wire everything together
```

## Build order (do these in sequence — each phase should run before the next)

### Phase 1 — Prove the model connection works
Build: `llm/client.py`, just a `generate(prompt) -> str` function.
- Send a plain text prompt to a running Ollama instance, return the response.
- **Test it manually**: run it against a trivial prompt ("say hello") before
  building anything else. If this doesn't work, nothing downstream will.
- Don't build streaming, vision, or JSON output yet — just prove text in,
  text out works end to end against your actual Ollama setup.

### Phase 2 — Wire up main.py with a stub pipeline
Build: `main.py` with `argparse` for `mode`, `--text`, `--answer`.
- Skip `--image`/`--video` for now — hardcode text input only.
- `check` mode: take the question + answer, send *one* combined prompt to
  `llm/client.py` asking "is this correct?", print the response.
- This gets you a fully working (if simplistic) check-mode loop, text only,
  no RAG yet. Confirms the whole chain: CLI → model → printed answer.

### Phase 3 — Add RAG grounding
Build: `rag/ingest.py`, `rag/retrieve.py`.
- Ingest: take a folder of `.txt` reference files, chunk them, embed them
  into a ChromaDB collection.
- Retrieve: given a question, pull back the most relevant chunks.
- Wire retrieval into check mode's prompt (prepend retrieved context before
  asking "is this correct?"). Verify answers actually improve/ground
  correctly with real reference material in `data/reference/`.

**Setup step — `data/chroma/` is gitignored, so a fresh clone has no
collection and grounding does nothing until you build one:**

```bash
python -m rag.ingest        # ~3,500 chunks, a few minutes on CPU
```

It reads `.txt` files from `data/reference/` and PDFs from `data/papers/`,
drops chart and OCR-garbage pages, and rebuilds the collection from scratch.
Re-run it after downloading new papers.

`retrieve()` drops anything further than `MAX_DISTANCE` (cosine, 0.60) so an
off-topic lesson is not handed irrelevant context. That number is a
compromise, not a clean cut — the on- and off-topic ranges overlap. See the
comment in `rag/retrieve.py` before changing it.

### Phase 4 — Build learn mode's core loop
Build: `core/decompose.py`, `core/session.py`.
- `decompose_question(question) -> list of steps`: ask the model to break
  the question into an ordered list of steps (each step = one prompt to
  show the student).
- `TutorSession`: holds the steps, current step index, and an
  `submit_answer(answer)` method that checks the current step and either
  advances or asks again.
- Test with a hardcoded question first — walk through all steps manually
  via the terminal before worrying about hints or error classification.

### Phase 5 — Add real feedback: error classification + escalating hints
Build: extend `core/decompose.py` with an `evaluate_step_answer()` that
classifies *why* an answer is wrong (not just right/wrong), and
`core/hints.py` that generates a hint whose specificity increases with
each wrong attempt on the same step.
- This is the piece that makes it feel like *teaching* instead of a quiz
  with retries — worth testing deliberately with a few wrong answers in a
  row to check the hints actually escalate.

### Phase 6 — Image input
Build: `vision/image_handler.py`.
- One function: given an image file, return a text transcription of the
  question (using the model's vision capability, if your chosen model has
  one — check what you pulled in Ollama supports images).
- Wire `--image` into `main.py`: read the image, get the transcription,
  feed it into the same learn/check flow from Phases 2–5. No new logic
  needed here — this phase is entirely about getting text *out* of an image.

### Phase 7 — Video input
Build: `video/frame_extractor.py`, `video/video_handler.py`.
- Extract frames from the video at some interval (OpenCV).
- Run each frame through the same image handler from Phase 6.
- If frames show different parts of the same question, you'll need to
  reconcile multiple frame transcriptions into one — decide how you want
  to handle that once you see what real extracted frames look like.

## Training track (runs alongside the numbered phases, not after them)

### Phase A — a transformer from scratch
Build: `training/train_tiny.py`. A char-level GPT in one file — tokenizer,
causal self-attention, residual blocks, training loop, sampling. No
`transformers`, no `Trainer`. The point is understanding the parts, not the
result.

### Phase B — session logging
Build: `sessionlog.py`.
- Append one JSON line per tutor turn to `.logs/sessions.jsonl`: timestamp,
  session id, mode, topic, provider/model, the student's message, the tutor's
  reply, the `[CORRECT]`/`[WRONG]` verdict and token counts.
- Attachment **metadata only** — type, name, size. Never the bytes.
- A logging failure must never break a lesson.
- This is the input to Phase C, so the fields have to be enough to rebuild a
  conversation in order.
- The chat history sidebar reads this log back: `GET /api/sessions` lists past
  lessons, `GET /api/sessions/<id>` rebuilds the messages array so a lesson can
  be resumed. That rebuild is the standing proof the fields are sufficient — if
  a new field stops being logged, resume breaks first.
- **Auth landed 2026-08-04** (`users.py`). Accounts, scrypt password hashing and
  cookie sessions; `list_sessions()` and `session_turns()` take a `user_id` and
  return only that student's lessons. The 32 log lines written before auth
  carried `user_id: null` and vanished from the sidebar; they were backfilled to
  `user_id: 1` in Session 8, and `null` now appears 0 times in the log.

### Phase C — LoRA fine-tune on logged sessions
Needs Phase B to have collected enough real lessons first. Phase A already
showed what too little data does: training on a 975-byte file drove train loss
to 0.90 while validation *climbed* to 3.59.

## Hardware note (relevant to testing at every phase)

8GB RAM + Intel Iris (no dedicated GPU) can run everything here *except*
the model itself at a usable speed. Point your Ollama client at a remote
instance (e.g. tunneled from a free Colab/Kaggle GPU notebook) rather than
`localhost` while developing. Everything else — RAG ingestion, frame
extraction, the session state machine — is lightweight enough to run
locally.

## Checking it still works

```bash
python -m evals.run                  # everything
python -m evals.run --only regress   # no model calls, no key, ~7 seconds
```

`evals/cases.jsonl` is 50 questions with known answers, 25 right and 25 wrong.
Every key was checked with sympy first — both directions, so a "wrong" answer is
proven wrong rather than just written differently. Model-generated keys were
wrong 2 times in 3 before the verification pass existed, and an eval with a bad
key fails you for being right.

`evals/regress.py` is 34 checks for bugs already fixed once — the unclosed
`<think>`, `NH3` not being raised to `NH^3`, the running footer, `_dedupe`
collapsing one page but not two, the login rate limiter, a bare `[CORRECT]`
reaching the student as an empty bubble, the `Check:` scaffolding line leaking
into a reply, and an open question being marked wrong. No model calls, so there
is no excuse to skip it.

**Run this before and after any prompt change.** Two regressions shipped here
because a change was checked structurally and never against real model output.

As of 2026-08-17, against Groq `llama-3.3-70b-versatile`: **50/50 on check mode,
34/34 regressions, 50/50 replies carrying a verdict signal, 0 unparsed.**

This is the first run since `CHECK_SIGNAL` gained its `[OPEN]` branch on
2026-08-14. It took two invocations: 48 cases landed, and q19 and q32 died on a
per-minute 429 after exhausting all four retries, so they were re-run alone with
`--case q19 q32 --jobs 1`. Both passed. Nothing was scored from a failed call —
the first run reported those two as `error`, not as wrong answers.

Two clean runs now, not one, but still not proof the marker problem is gone.
`CHECK_SIGNAL` asks for a `Check: correct answer is X; student wrote Y` line
before the marker, plus a rule that equivalent forms count as matching. The rule
is the part that matters: without it the model compared the two answers as *text*
and failed `3n + 2` against `2 + 3n`. With it, correct answers scored 25/25. Three
attempts have changed this string and two made things worse — read the comments
above `CHECK_SIGNAL` in `prompts.py` before trying a fourth.

`[OPEN]` is the third. It exists because check mode marked *"flashcards"* wrong
for revising, on the grounds that the retrieved reference chunks did not mention
them. It maps to the same `None` verdict a missing marker gives, so no other
layer changed. The risk it carries is the model reaching for it on questions that
do have answers; `evals/run.py` keeps its own `(CORRECT|WRONG)` regex on purpose,
so an `[OPEN]` there counts as *no signal* and shows up in the `verdict source`
line of the report. Watch that line.

Measured 2026-08-17: `unparsed 0` across all 50, so the model reached for `[OPEN]`
on none of the questions that do have answers. One run, on one model.

The `Check:` line is scaffolding and never reaches the student; `_CHECK_LINE_RE`
strips it. Reword one and you must reword the other.

The score moves about 2 points between identical runs because temperature is not
pinned, so treat anything under 3 points as noise and run it twice. A 50-case run
costs roughly a quarter of Groq's free daily token budget, which works out at
about four runs a day — that, not the code, is the real limit on how fast prompt
changes
can be tested.

Numbers in this file go stale the moment they are not re-run. `12/12
regressions` sat here for two commits after the count reached 19.

The check-mode prompt and the `[CORRECT]`/`[WRONG]` parser both live in
`prompts.py`, shared by `app.py`, `main.py` and the evals. Change the marker
format and you must change both — the instruction that asks for it and the
regex that reads it are deliberately next to each other.

## Definition of done, per phase

- [x] Phase 1: a script that sends one prompt to Ollama and prints the reply
- [x] Phase 2: `python main.py check --text "..." --answer "..."` runs end to end
- [x] Phase 3: check mode's answers visibly use ingested reference material
      — ticked from Session 3 but **only true since 2026-08-02**. The collection
      was empty until then, so `retrieve()` returned nothing and every lesson
      ran ungrounded. Now 3,508 chunks from `data/reference/` and `data/papers/`
- [x] Phase 4: `python main.py learn --text "..."` walks through steps interactively
- [x] Phase 5: three wrong answers in a row produce three *different*,
      increasingly specific hints
- [x] Phase 6: `--image` produces the same learn/check flow as `--text`
      — done in the web app (`vision/image_handler.py`, wired into
      `/api/start`, `/api/reply`, `/api/check`) and in the CLI via
      `--image`, on both the Ollama and Groq providers
- [x] Phase 7: `--video` produces the same flow as `--image`
      — `video/frame_extractor.py` shells out to ffmpeg rather than OpenCV,
      which is not what the spec above says. `cv2` is a ~60MB wheel and ffmpeg
      was already installed. The `mpdecimate` filter drops near-duplicate
      frames, so a static page costs 1 vision call instead of one per sample.
      Multiple distinct frames are merged by one text-model call in
      `video/video_handler.py`. Run live on Groq in both learn and check mode.

      **mpdecimate only catches a still camera.** Measured on a 10s clip of one
      page with a slow zoom and drift: 5 frames of a possible 5 survive, so one
      page costs 5 vision calls. No `hi`/`lo`/`frac` setting fixes it — the
      loosest one that collapses the handheld clip to 1 also collapses a real
      two-page clip to 1, which loses content. `_dedupe()` catches it after
      transcription, so the answer is still right and the merge call is saved,
      but the vision calls are already spent. A perceptual hash before
      transcription would fix it; 48x48 separated cleanly on the two test
      clips and smaller sizes did not, which is one data point, not a
      threshold. Needs real filmed pages before it is worth wiring in
- [x] Phase A: `training/train_tiny.py` trains on CPU and samples readable text
- [ ] Phase B: a finished lesson appears in `.logs/sessions.jsonl` as one JSON
      line per turn, in order, with non-zero token counts on both providers,
      and replaying those lines reconstructs the conversation
      — replay is done and proven live: the sidebar resumes a lesson from the
      log alone and the tutor continues rather than restarting. Still open:
      token counts have only ever run live on Groq, never on Ollama
- [ ] Phase C: a LoRA adapter trained on logged sessions beats the base model




Build and test one phase before starting the next — each one should be
runnable on its own, even if the later phases don't exist yet.