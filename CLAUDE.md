# Working notes for Claude

## The project

SAT/A-level tutor. `readme.md` holds the phase roadmap and the definition of
done for each phase — check it before starting anything, and build phases in
order. `devlog.md` is the running history, newest session at the bottom.

Two front ends over the same core: `app.py` (Flask + `static/index.html`) and
`main.py` (CLI). They share `llm/`, `rag/`, `vision/`. Their tutor prompts have
drifted apart three times now — if you change one, check the other.

## How I like to work

**Ask before writing code I might want to type myself.** I often want to read
every line and type it in, because that is how I learn this. If I say "let me
code it", give me the design and the code to work from, not edits to my files.
If I say "just do it", go ahead and write it.

**Explain unfamiliar Python as you go.** Short, plain explanations of the syntax
itself — what `rf"..."` means, why `.b64encode(...).decode()` is two steps, what
a mutually exclusive argparse group does. Assume the logic is clear and the
syntax is not.

**Plain English everywhere**, in explanations and in the product. Short
sentences, everyday words. The tutor prompt enforces this for students; hold the
same bar when talking to me.

## Verifying

**Run the thing before saying it works.** Prompt changes especially — two
regressions this project shipped because a change was checked structurally and
never against real model output. A live turn through Groq costs almost nothing.

Report what actually happened, including the failures. If a generated answer key
is wrong, say so with the arithmetic. Do not round a partial result up to "done".

## Secrets

Keys live in `.env` only. It is gitignored; `.env.example` is the committed
template and must stay blank. Three keys have leaked here — pasted into chat,
written into `.gitignore`, written into `.env.example` — so treat any key that
touches a tracked file as burned and say it needs rotating.

`hooks/pre-commit` blocks commits containing key patterns. A fresh clone needs
`git config core.hooksPath hooks` once.

## Git

Work on `master` and push there; that is the branch this repo actually uses.
Commit and push only when asked. Write the devlog entry for a session when I ask
for it, matching the existing structure — including a "Known issues" section
that is honest about what is still broken.

## Things that keep biting

- The default Groq vision model reasons out loud; `<think>` blocks must be
  stripped from transcriptions
- `pypdf` loses parentheses and ligatures, so `g(x)` can extract as `gx^h`
- Past-paper questions are model-generated, and their answer keys were wrong
  2 times in 3 before the verification pass existed
- `_SIGNAL_RE` is anchored to end-of-string, so `[CORRECT]`/`[WRONG]` must stay
  last in a tutor response
