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

## Hardware note (relevant to testing at every phase)

8GB RAM + Intel Iris (no dedicated GPU) can run everything here *except*
the model itself at a usable speed. Point your Ollama client at a remote
instance (e.g. tunneled from a free Colab/Kaggle GPU notebook) rather than
`localhost` while developing. Everything else — RAG ingestion, frame
extraction, the session state machine — is lightweight enough to run
locally.

## Definition of done, per phase

- [x] Phase 1: a script that sends one prompt to Ollama and prints the reply
- [x] Phase 2: `python main.py check --text "..." --answer "..."` runs end to end
- [x] Phase 3: check mode's answers visibly use ingested reference material
- [x] Phase 4: `python main.py learn --text "..."` walks through steps interactively
- [x] Phase 5: three wrong answers in a row produce three *different*,
      increasingly specific hints
- [ ] Phase 6: `--image` produces the same learn/check flow as `--text`
      — done in the web app (`vision/image_handler.py`, wired into
      `/api/start`, `/api/reply`, `/api/check`); the `--image` CLI flag
      is still outstanding
- [ ] Phase 7: `--video` produces the same flow as `--image`




Build and test one phase before starting the next — each one should be
runnable on its own, even if the later phases don't exist yet.