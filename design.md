# Design notes

Proposals that are not built yet. Once something here ships, it moves to
`devlog.md` and comes out of this file.

---

## Paper intent + topic extraction as a structured call

**Status: SHIPPED 2026-08-01 in `9b63b6c`.** Written up here, built the same day.
The full account is in `devlog.md` under Session 5 — read that, not this. Kept
below only because the reasoning is worth having, in particular why a classifier
here does not contradict the Session 4 decision against one.

**One change from what is written below.** The prefilter needed its own noun
pattern rather than reusing `_PAPER_NOUN`, which keeps bare `paper` plural-only
so the fallback behaves as before. Without that, `why won't you give me the
paper` never reached the classifier.

### The problem

A real transcript, Groq / `llama-3.3-70b-versatile`, lesson topic set to the
whole sentence `Can you please help me fetch AS level papers of Computer
Science`:

| # | what happened | cause |
|---|---|---|
| 1 | `can you not fetch the entire pdf` was ignored as a request | `_NOT_PAPERS_RE` matched `not` … `pdf`, so `_wants_papers` returned False and the turn went to the tutor |
| 2 | the tutor replied that it cannot download files | prompt contradiction, see below |
| 3 | student asked for **SAT**, got **AS level Computer Science** | `_TOPIC_IN_REQUEST_RE` found no stated topic, so it fell back to the lesson topic |
| 4 | the reply printed the lesson topic verbatim as a subject | the lesson topic is a whole sentence and `_looks_like_topic` passes it |

Verified rather than guessed:

```
_wants_papers("can you not fetch the entire pdf")      -> False   (negation matched)
_TOPIC_IN_REQUEST_RE on "can you fetch SAT papers"     -> no match
_TOPIC_IN_REQUEST_RE on "past papers on SAT"           -> 'SAT'
_looks_like_topic("Can you please help me fetch ...")  -> True
```

None of this is the model reasoning badly. `llama-3.3-70b` can trivially tell
that "can you fetch SAT papers" wants SAT papers — it was never asked. A regex
decided the topic and the model never saw the question. **Retraining would fix
nothing here.**

Failure 2 is the one genuine prompt bug, and it is a contradiction rather than a
model error. `TUTOR_SYSTEM_PROMPT` says both:

- lines 58–61 — *a question about what this app can do … say honestly if you
  cannot do it*
- lines 62–64 — *never tell them you cannot get past papers*

The model classified the message as a capability question and applied the first
rule. It followed the prompt; the prompt disagrees with itself. **Fix that
separately** — this design makes that phrasing stop reaching the tutor, but
other phrasings will still hit the contradiction.

### The shape

Three pieces replace the single `_wants_papers` gate in `/api/reply`:

```
_mentions_papers(text)              cheap regex prefilter — decides whether to spend a call
_paper_intent(msg, lesson, **llm)   one structured call — returns {wants_papers, topic}
_papers_for_chat(topic, key)        now takes a resolved topic, does no extraction
```

`_wants_papers`, `_TOPIC_IN_REQUEST_RE` and `_looks_like_topic` all stay as the
fallback when the call fails. Nothing is deleted.

### Why this does not contradict the Session 4 decision

Session 4 rejected a classifier because it would cost a call on *every* tutor
turn, on the common path where the student is just answering a question. That
reasoning still holds. It does not have to run on every turn — the keyword rule
becomes a prefilter, and the call happens only when a message mentions papers at
all. Those turns are rare.

### The prefilter

```python
_MENTIONS_PAPERS_RE = re.compile(rf"\b{_PAPER_NOUN}\b", re.IGNORECASE)

def _mentions_papers(text: str) -> bool:
    """Cheap gate — only messages that mention papers cost an intent call."""
    return bool(text) and bool(_MENTIONS_PAPERS_RE.search(text))
```

Deliberately much wider than `_wants_papers`: no verb requirement and **no
negation cancel**. Casting wide is the point — the regex stops adjudicating and
only decides whether a question is worth asking. A student answering
`photosynthesis happens in the chloroplast` never trips it. `explain this paper
I uploaded` does trip it, costs one call, and gets the right answer instead of a
lucky one.

### The call

One call resolves intent *and* topic together, including shortening a verbose
lesson topic. That is what kills failure 4 without a separate fix.

```python
PAPER_INTENT_PROMPT = (
    "You decide whether a student is asking to be given past exam paper files, "
    "and what subject those papers should be about.\n\n"
    "Return ONLY a JSON object. No prose, no code fences:\n"
    '{{"wants_papers": true or false, "topic": "subject" or null}}\n\n'
    "wants_papers is true when the student wants actual paper files handed to them, "
    "including when it is phrased as a complaint or a rhetorical question "
    '("can you not just fetch the whole pdf", "why won\'t you give me the paper").\n'
    "wants_papers is false when they ask what a past paper is, discuss a paper they "
    "already uploaded, or are simply answering a lesson question.\n\n"
    "topic is the exam subject to search for, as a short phrase a search engine would "
    'accept: "SAT", "trigonometry", "AS level Computer Science". '
    "Take it from the student's message when they name one. Otherwise fall back to the "
    "lesson topic below, shortened to just the subject — the lesson topic may be a full "
    "sentence, so strip it down to the subject. Use null only if neither gives a subject.\n\n"
    "Lesson topic: {lesson_topic}\n"
    "Student message: {message}"
)
```

The braces around the JSON example are doubled because the prompt goes through
`.format()`. Single braces raise `KeyError`.

```python
_JSON_OBJ_RE = re.compile(r'\{.*\}', re.DOTALL)


def _paper_intent(user_input: str, lesson_topic: str, **llm) -> dict:
    """Decide whether this turn is a papers request, and for what subject.

    Falls back to the keyword rules on any failure. A flaky model must not cost
    the student the feature — same policy as _verify_questions.
    """
    fallback = {
        "wants_papers": _wants_papers(user_input),
        "topic": _stated_topic(user_input) or lesson_topic.strip(),
    }

    try:
        raw = chat([{"role": "user", "content": PAPER_INTENT_PROMPT.format(
            lesson_topic=lesson_topic.strip() or "(none)", message=user_input)}], **llm)
    except Exception:
        return fallback

    m = _JSON_OBJ_RE.search(raw or "")
    if not m:
        return fallback
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return fallback

    # A model that returns the wrong shape is a failed call, not a "no".
    if not isinstance(data.get("wants_papers"), bool):
        return fallback

    topic = data.get("topic")
    topic = topic.strip() if isinstance(topic, str) else ""
    return {"wants_papers": data["wants_papers"], "topic": topic}
```

`_JSON_OBJ_RE` is greedy on purpose — models wrap JSON in fences and prose, and
the outermost `{...}` is the object you want.

`_stated_topic()` is the current extraction lifted out of `_papers_for_chat` so
both paths share one implementation:

```python
def _stated_topic(user_input: str) -> str:
    """The subject named in the request itself, or empty."""
    m = _TOPIC_IN_REQUEST_RE.search(user_input)
    return _TOPIC_TRAIL_RE.sub("", m.group(1)).strip() if m else ""
```

### Wiring into `/api/reply`

Replacing the current `if _wants_papers(user_input):` block:

```python
    if _mentions_papers(user_input):
        intent = _paper_intent(user_input, topic,
                               model=model, host=host, provider=provider, api_key=api_key)
        if intent["wants_papers"]:
            reply, papers = _papers_for_chat(intent["topic"], tavily_key)
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": reply})
            return jsonify({
                "response": reply,
                "messages": _strip_images(messages),
                "done": False,
                "correct": None,
                "papers": papers,
            })
        # Not a papers request after all — fall through to the tutor.
```

The fall-through matters. With a wide prefilter, a "no" from the classifier must
let the turn continue to the tutor as normal, not dead-end.

`_papers_for_chat` loses its extraction and keeps `_looks_like_topic` as a
backstop on whatever it is handed:

```python
def _papers_for_chat(topic: str, tavily_key: str) -> tuple[str, list]:
    """Fetch papers for an already-resolved topic. Returns (reply text, papers)."""
    topic = (topic or "").strip()
    if not topic:
        return ("Which topic should I look for? Tell me the subject and I'll find papers on it.", [])
    if not _looks_like_topic(topic):
        return (f'I\'d be searching for "{topic}", which doesn\'t look like a '
                "subject. Which topic should I find papers on?", [])
    ...
```

### What it fixes

| transcript failure | fixed by |
|---|---|
| 1 — "can you not fetch the entire pdf" read as a refusal | prefilter drops the negation cancel; classifier reads it as a request |
| 2 — tutor denied it could fetch | **not fixed.** That turn no longer reaches the tutor, but the prompt contradiction remains |
| 3 — asked SAT, got Computer Science | classifier extracts `SAT` where the regex needed `papers on SAT` |
| 4 — lesson topic is a whole sentence | classifier shortens it to `AS level Computer Science` |

### Cost

One extra call, only on turns that mention papers. Prompt is roughly 200 tokens,
output about 20. On Groq that is a few hundred milliseconds against a papers
flow that already takes 20–100 seconds for search and download, so it is noise.
Ordinary tutoring turns are untouched.

### Scope

`/api/papers` (the 📄 button) is unaffected — it already receives an explicit
topic. `main.py` is unaffected, because the CLI has no past-papers code at all.

### Testing

Offline first, patching `chat` so the classifier is deterministic. This is the
part that catches a helper that is defined but never called, which has now
happened twice in this codebase:

```python
import app as A, json
LESSON = "Can you please help me fetch AS level papers of Computer Science"

A.chat = lambda msgs, **k: json.dumps({"wants_papers": True, "topic": "SAT"})
print(A._paper_intent("can you fetch SAT papers please", LESSON))   # topic == 'SAT'

A.chat = lambda msgs, **k: "Sure!\n```json\n{\"wants_papers\": false, \"topic\": null}\n```"
print(A._paper_intent("what is a past paper?", LESSON))             # fences tolerated

def boom(*a, **k): raise RuntimeError("groq down")
A.chat = boom
print(A._paper_intent("give me past papers", "trigonometry"))       # falls back, still works

for t in ["photosynthesis happens in the chloroplast", "B", "the answer is 42"]:
    assert not A._mentions_papers(t), t
```

Then one live run per transcript failure — `can you not fetch the entire pdf`,
and `can you fetch SAT papers please` with a junk lesson topic — confirming the
first fetches instead of denying, and the second returns SAT papers instead of
Computer Science.

### Open questions

- Does the prefilter need a length cap? A very long message that happens to
  contain "papers" costs a call. Probably fine, worth watching.
- Should a classifier "no" be cached for the turn, so a retry of the same
  message does not pay twice?
- The lesson topic is still never validated at `startLearn`, which is where the
  junk enters. This design copes with a bad topic; it does not stop one being
  set.

---

## Also outstanding, not designed yet

- **The tutor denies it can receive uploaded files.** Found while testing the
  classifier fall-through: `explain this paper I uploaded` reaches the tutor,
  which answers *"As a text-based AI model, I don't have the capability to
  receive or access files"*. That is false — `/api/upload` handles PDFs and
  images. Same shape as the past-papers denial fixed in `c10fe69`, and probably
  the same fix: the honesty rule needs to know what the app can actually do.
- **Check mode has no prompt of its own.** `api_check` hands
  `TUTOR_SYSTEM_PROMPT` to a task that is not Socratic, so a prompt saying
  *never give the full answer unprompted* is asked for a verdict. The two
  branches also differ in tone, since only one passes a system prompt at all.
- **The two `TUTOR_SYSTEM_PROMPT`s have drifted for a fourth session.** Copying
  the web prompt into `main.py` is a trap: the CLI would promise past papers it
  cannot fetch, because the fetching code is entirely in `app.py`. They want to
  be one shared constant *and* the papers helpers want lifting into a shared
  module first.
- **No timeout on the graph sandbox.** `for i in range(10**9)` passes AST
  validation and hangs the request. Only a subprocess fixes that.

---

## Phase C: what to copy from MathGPT, and what has to be fixed first

Not a code proposal. An ordering argument, written down because it will be
re-litigated when Phase C comes up and the evidence is easy to lose.

### The reference point

**Mathpresso** (Seoul), with **Upstage** and **KT**, built **MathGPT** on
**Llama 2**, documented on Meta's own blog. Supervised fine-tuning on
proprietary question-and-solution pairs from **QANDA**, their existing math app
running across 50 countries, plus data augmentation and deliberately added
maths-expression data to strengthen LaTeX interpretation. They claim a record on
primary and secondary school maths benchmarks.

That is Phase C, already done by someone else, and it worked. The pattern —
open base model, fine-tuned on solution traces logged from your own tutoring
platform — is the one this project's readme describes.

### Two things worth taking from it

**Their stated reason for choosing open weights was data control.** A hosted
model would have meant handing proprietary problem-solution pairs to someone
else. The equivalent here is student text, from minors, currently posted to
Groq with no consent flow and no retention policy. If the privacy issue in the
Session 5 known-issues list ever becomes real, this is the argument for the
Ollama path that is already the default.

**They trained on maths-expression data on purpose**, because notation is where
a general model degrades first.

### The ordering argument, which is the point of this entry

`pypdf` turns `g(x)` into `gx^h`. That is currently filed as a lesson-quality
problem. It is not — it is a **Phase C prerequisite**.

Phase C trains on `.logs/sessions.jsonl`. Those logs contain tutor turns about
uploaded PDFs and generated past-paper questions, and the mangled notation goes
into the log exactly as the model saw it. Bad extraction does not just degrade
one lesson, **it poisons the training set**, and it does so invisibly — the
damage is in the data long before anyone runs a training job.

So the sequence has to be:

1. Clean up extracted PDF text so notation survives
2. Vision transcription for the 4 scanned papers that currently contribute nothing
3. *Then* accumulate logged sessions worth training on
4. *Then* Phase C

Doing 3 before 1 means throwing away however many months of logs it took to
collect, or training on corrupted maths and not finding out until the adapter
is worse than the base model.

### Corollary for the log

Nothing currently records **which retrieved chunks** produced a tutor turn, or
whether a turn was grounded at all. For fine-tuning, an ungrounded turn and a
grounded one are different kinds of example, and there is no way to tell them
apart after the fact. Worth logging the retrieval sources before the log becomes
training data, not after.

### Not the same as competing with MathGPT

Mathpresso had QANDA's existing user base across 50 countries feeding it data.
This project has `.logs/sessions.jsonl` with tens of turns. The gap is data, not
code, and no amount of building closes it. Phase C stays last for that reason.
