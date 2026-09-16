# EdKernel — Kernel API (`/v1/`)

**EdKernel is a kernel, not an app.** This document is the public contract. The
web UI shipped in this repo is one reference client; you can build any front end
— mobile, an LMS plugin, a bot, a school portal — on top of the same `/v1/` API,
like a distribution over a kernel. The backend contract below is fixed;
everything above it is yours.

What the kernel gives you is the *education-specific* orchestration, not a raw
LLM wrapper:

| Primitive | Endpoint | What it does |
|---|---|---|
| List curricula | `GET /v1/curricula` | Discover available classes |
| Get topics | `GET /v1/curricula/<id>/topics` | Topic tree for a curriculum |
| Check an answer | `POST /v1/check` | Verdict + feedback on a submitted answer |
| Start a lesson | `POST /v1/tutor/start` | Opens a Socratic session that withholds the answer |
| Continue a lesson | `POST /v1/tutor/reply` | Next hint up the ladder; never gives it away |
| Check handwritten working | `POST /v1/check/working` | Vision → per-step transcription → first wrong step |
| Extract questions from a PDF | `POST /v1/questions/extract` | Past paper → structured question list |
| Record progress | `POST /v1/progress` | Log a topic attempt (right/wrong) |
| Read progress | `GET /v1/progress/<id>` | Mastery per topic |
| Manage keys | `GET/POST/DELETE /v1/keys` | Self-service API keys |

A UI can build the whole tutoring loop from these: **discover** (curricula/topics)
→ **teach/check** (tutor, check, check/working) → **track** (progress).

Reading handwriting is not the moat (frontier models do that). The value is the
pedagogy: per-step, method-mark-style checking that teaches rather than solves.

---

## Base URL

```
https://<your-deployment>/v1
```
The reference deployment runs on AWS ECS Fargate behind an ALB.

## Authentication

Every endpoint except `/v1/ping` requires a **Bearer token**:

```
Authorization: Bearer <api_key>
```

Obtain an initial key from your EdKernel account (the account's API-keys page, or
from an admin). Once you have one, `POST /v1/keys` mints more and
`DELETE /v1/keys/<id>` revokes them. A missing or invalid key returns **401**.

Keys are stored SHA-256–hashed server-side; the raw token is shown **once** at
creation and never again.

## Rate limiting

**20 requests/minute per key owner**, across all endpoints (key management
included — minting keys in a loop is abuse too). Over the limit returns **429**
with a `Retry-After` header (seconds). The per-provider LLM daily/minute limits
of whatever model you point at still apply on top of this.

## Choosing the model

Every LLM-backed endpoint accepts optional overrides so a client picks its own
provider without a redeploy. JSON endpoints read them from the body; the
file-upload endpoints read them from multipart form fields:

| Field | Meaning | Default |
|---|---|---|
| `provider` | `groq` \| `ollama` \| `bedrock` | `ollama` |
| `model` | text model id | `gemma4` |
| `api_key` | provider key (falls back to server env) | — |
| `host` | Ollama host / Bedrock region | `http://localhost:11434` |
| `vision_model` | override the vision model (`/check/working` only) | server default |

## Error format

All errors are JSON: `{"error": "<message>"}` with an HTTP status:

| Status | Meaning |
|---|---|
| 400 | Missing/invalid required field |
| 401 | Missing or invalid API key |
| 422 | Input could not be processed (bad PDF, unreadable image) |
| 429 | Rate limited (see `Retry-After`) |

---

## Endpoints

### `GET /v1/ping`
Health check. No auth.
```json
→ 200  {"ok": true}
```

---

### `POST /v1/check`
One-shot answer check.

**Body**
```json
{
  "question": "Solve 2x + 7 = 19",     // required
  "answer":   "x = 6",                  // required
  "context":  "",                        // optional grounding text
  "provider": "groq", "model": "openai/gpt-oss-120b"   // optional overrides
}
```
**Response**
```json
{ "feedback": "Correct — you isolated x cleanly.", "correct": true }
```
`400` if `question` or `answer` is missing.

---

### `POST /v1/tutor/start`
Open a Socratic lesson. The tutor guides; it does **not** hand over the answer.

**Body**
```json
{
  "topic":         "quadratic factorising",   // required
  "context":       "",                          // optional (e.g. curriculum text)
  "question_bank": ""                           // optional questions to draw from
}
```
**Response**
```json
{
  "reply":    "Let's start. What two numbers multiply to 6 and add to 5?",
  "correct":  null,
  "messages": [ {"role": "system", "..."}, {"role": "assistant", "..."} ]
}
```
Pass `messages` back into `/v1/tutor/reply` to continue the session (the API is
stateless — the client holds the transcript).

---

### `POST /v1/tutor/reply`
Continue a lesson. Send the running transcript plus the student's latest message.

**Body**
```json
{
  "messages":     [ ...from the previous call... ],   // required
  "message":      "is it 2 and 3?",                    // required
  "wrong_streak": 0                                     // optional; climbs the hint ladder
}
```
**Response**
```json
{ "reply": "Yes — so how do you write the factors?", "correct": true,
  "messages": [ ...updated transcript... ] }
```
`wrong_streak` drives the hint ladder: higher = more explicit help, but the
final answer is still withheld until the student produces it.

---

### `POST /v1/check/working`  ← the flagship
Upload a photo of handwritten working; get back the per-step transcription and
the first step that does not follow — the same thing a Cambridge examiner checks
when awarding method marks.

**Multipart form fields**
```
file          image of the working (JPEG/PNG)   — required
provider, model, api_key, host, vision_model    — optional overrides
```
**Response**
```json
{
  "steps":       ["2x - 5 = 9", "2x = 4", "x = 2"],   // transcribed lines
  "boxes":       [[x,y,w,h], ...],                     // bounding box per step
  "image_size":  [height, width],                      // of the preprocessed page
  "error_index": 1,                                    // first wrong step (0-based), or null
  "explanation": "2x = 4 should be 2x = 14 ...",       // why, or null
  "annotated":   "<base64 JPEG>",                       // page with the error boxed red
  "trace":       ["Perceived 3 lines.", "Line 2 ..."]  // perceive→decide→act log
}
```
`error_index: null` means every step follows. `422` if the image is unreadable.

---

### `POST /v1/questions/extract`
Turn a past-paper PDF into a structured question list.

**Multipart form fields**
```
file      the PDF                     — required
provider, model, api_key, host        — optional overrides
```
**Response**
```json
{ "questions": [ {...}, {...} ], "count": 12 }
```
`422` if no questions could be parsed.

---

### `GET /v1/curricula`
List the curricula available on the server, so a UI can render the class list.
```json
→ 200  {"curricula": [ {"id": "gcse-maths", "name": "GCSE Mathematics",
                        "subjects": ["Number", "Algebra", ...]}, ... ]}
```

---

### `GET /v1/curricula/<id>/topics`
The topic tree for one curriculum (name, subtopics, objectives per topic).
```json
→ 200  {"curriculum": "gcse-maths", "topics": [ {...}, {...} ]}
```
Returns `"topics": []` if the curriculum has none.

---

### `POST /v1/progress`
Record one topic attempt. **Scoped to the API key's owner** — a multi-student
front end issues one key per student.

**Body**
```json
{ "curriculum": "gcse-maths",   // required
  "topic":      "Algebra",       // required
  "correct":    true }           // optional (default false)
```
**Response** `{"ok": true}`. `400` if `curriculum` or `topic` is missing.

---

### `GET /v1/progress/<id>`
Read this key owner's mastery for a curriculum.
```json
→ 200  {"curriculum": "gcse-maths",
        "progress": [ {"topic_id": "Algebra", "attempts": 8, "correct": 6,
                       "last_seen": 1726300000}, ... ]}
```

---

### API key management

```
GET    /v1/keys              → {"keys": [ {id, label, created, ...}, ... ]}
POST   /v1/keys  {"label"}   → {"token": "<shown once>", "note": "..."}
DELETE /v1/keys/<id>         → {"ok": true}
```

---

## Quick start

```bash
# health
curl https://<host>/v1/ping

# check an answer
curl -X POST https://<host>/v1/check \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"question":"Solve 2x+7=19","answer":"x=6","provider":"groq","model":"openai/gpt-oss-120b"}'

# check handwritten working
curl -X POST https://<host>/v1/check/working \
  -H "Authorization: Bearer $KEY" \
  -F file=@working.jpg -F provider=groq -F model=openai/gpt-oss-120b
```

## Building your own front end

The kernel is stateless and UI-agnostic. A client is responsible for:
1. **Holding session state** — for tutoring, keep the `messages` array and pass
   it back each turn.
2. **Rendering** — steps, the `annotated` image (base64 JPEG), and math (the
   text uses LaTeX; render with KaTeX/MathJax).
3. **Grounding** — pass your curriculum text in `context` / `question_bank` so
   feedback matches the student's actual syllabus (GCSE, Cambridge, Kurikulum
   Merdeka, …).

Everything else — layout, language, platform — is yours.

**Working example:** [`examples/reference_client.html`](../examples/reference_client.html)
is a complete tutoring UI in one ~150-line file, built only on `/v1/` — no build
step, no dependency on the main web app. Open it, point it at a deployment, paste
an API key, and teach. It looks nothing like the shipped web UI, which is the
whole point: same kernel, swappable front end.

**CORS:** `/v1/` sends `Access-Control-Allow-Origin: *`. It's safe because auth
is a Bearer *header*, not a cookie — there are no credentials for a hostile
origin to ride — so a browser UI on any domain can call the kernel directly.
