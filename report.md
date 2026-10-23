# EdKernel — Technical Report
### OpenCV AI Competition 2026 (powered by AWS)
**Team:** Metis · Solo entrant · Submission deadline: 26 Oct 2026

---

## 1. Problem

A student stuck on a maths problem gets one bit of information from almost every tool available: right, or wrong. If it is wrong, they are told to try again. They already knew that. What they do not know is *where* it went wrong — whether the setup was fine and they dropped a sign on line three, or whether the whole approach was doomed from line one.

That is the difference between a grade and a teacher. A human tutor looking at a sheet of handwritten working does not mark the final answer. They run a finger down the page and stop at the first line that does not follow from the one above it.

**EdKernel does that.** A student photographs their handwritten working. OpenCV 5 finds the page, flattens it, cleans it, and cuts it into individual steps. Each step is compared against the step above it. The tutor reports which line the error is on and teaches from there — not from the bottom of the page.

The impact is access. Per-step feedback on your own handwriting is the part of tutoring that costs money, and it is the part no free tool currently provides.

### The need is measured, not assumed

Three education systems, one shared gap — students are graded on *answers* but learn from *process*, and nobody is checking the process at scale.

- **United States.** Only **28% of 8th graders** and **22% of high-school seniors** are proficient in mathematics — the lowest in over 20 years — and the decline is worst for lower-performing students, widening the equity gap. Meanwhile **400,000+ classrooms** are vacant or staffed by underqualified teachers, and math-teacher graduates fell 36% (2012–2020). The proven intervention — one-to-one per-step feedback — is exactly what is unequally distributed. ([EdSource](https://edsource.org/2025/math-crisis-in-america-california/740849), [Dr. M. Lynch](https://www.drmattlynch.com/this-one-crisis-will-reshape-education-forever-what-you-need-to-know-for-fall-2026/))
- **Cambridge IGCSE / A-Level.** Examiner reports are consistent: students lose marks **not from lack of knowledge but from process** — skipping intermediate steps and failing to connect their reasoning, which forfeits the **method marks (M)** awarded for a visible, correct chain of working. ([The Brilliant Brains](https://thebrilliantbrains.com/how-do-examiners-mark-a-level-papers/), [Edflik](https://www.edflik.com/blog/inside-cambridge-examiner-reports-what-igcse-a-level-markers-want-to-see-in-written-explanations/)) EdKernel's step checker verifies exactly what earns a method mark: *does each line follow from the one above?* This is the sharpest fit — a documented pain that maps one-to-one to the tool.
- **Indonesia.** PISA 2022 mathematics: **364 vs the OECD's 463**, among the lowest since 2001, with a named root cause being teachers' own pedagogic and numeracy limitations. The government already runs a national teacher-support platform (Merdeka Mengajar). ([OECD](https://www.oecd.org/en/publications/pisa-2022-results-volume-i-and-ii-country-notes_ed6fbcc5-en/indonesia_c2e1ae0e-en.html)) A foreign app UI will not be adopted here — but a local team can build a Bahasa front end on EdKernel's `/v1/` kernel API, grounded in Kurikulum Merdeka. Integration freedom a monolithic app cannot offer.

### Why this is not "just use ChatGPT"

Reading handwritten maths is no longer a differentiator — frontier multimodal models do it, and do it well. We do not try to out-read them, and this report does not claim to. OpenCV's job here is the one thing those models **cannot** do reliably: **deterministic spatial grounding** — producing the verifiable pixel coordinates that let the system box the *exact* wrong line on the student's page. Ask a multimodal LLM "which pixel is the error on" and it hallucinates a location; `findContours` does not. That grounding is auditable, runs offline, and costs nothing per call.

On top of that grounding, EdKernel's defensible value is the combination a general chatbot does not ship: **per-step, method-mark-style checking, grounded in a specific exam board or national curriculum, that withholds the answer** (teaches rather than solves) and **surfaces a class-wide misconception map to teachers**. A student pasting working into ChatGPT gets the answer handed over — curriculum-blind, un-located, and counter-productive for learning. The `/v1/` API is documented so a school can drive this from the LMS it already uses; the shipped web UI is one reference client, not the product.

---

## 2. Architecture

```
  student browser
       |  HTTPS
       v
  ECS Fargate (Flask app)          <-- deployed, live
       |
       +-- core/vision/            <-- OpenCV 5 pipeline
       |     preprocess.py         (rectify, binarise, deskew)
       |     segment.py            (morphology → step boxes)
       |     step_checker.py       (5-stage perception→action loop)
       |
       +-- core/rag/               <-- ChromaDB RAG over syllabus + past papers
       |     ingest.py             (PDF → chunks; OpenCV for maths-heavy pages)
       |     retrieve.py
       |
       +-- core/llm/               <-- model client (Groq / Bedrock)
       |
       +-- users.db (SQLite)       <-- per-student progress, misconception tags
       |
       +-- /teacher                <-- teacher dashboard (progress, topic heatmap)

  AWS services: ECS Fargate, ECR, S3 (pending), RDS (pending), CloudWatch
```

### OpenCV 5 pipeline (the hot path)

Every uploaded image passes through these stages before any model call is made
(`core/vision/preprocess.py`, `core/vision/segment.py`):

| Stage | OpenCV call | Purpose |
|---|---|---|
| 1. Page detection | `bilateralFilter` → `Canny` → `morphologyEx` → `findContours` → `approxPolyDP` | Find the paper's four corners in a phone photo |
| 2. Rectification | `getPerspectiveTransform` → `warpPerspective` | Flatten a page photographed at an angle |
| 3. Deskew (no page found) | `adaptiveThreshold` + `morphologyEx` ink mask → `findContours` → `minAreaRect` seed → projection-profile search over `warpAffine` rotations | Straighten a rotated page when no clean page edge is visible |
| 4. Binarisation | `adaptiveThreshold` (Gaussian, 25px block) | Handle uneven desk lighting; isolate ink from background |
| 5. Step segmentation | `morphologyEx` (horizontal close) + `dilate` → `findContours` → `boundingRect` → row merge → line-shape filters | One bounding box per line of working |
| 6. Grounding | `rectangle` + `putText` → `imencode` | Draw the red box on the exact wrong line of the student's photo |

The output is a list of bounding boxes. The number of model calls made downstream equals the number of boxes returned. OpenCV does two load-bearing jobs here, neither of which is "reading": it **decides the shape of inference** (box count = tool-call count), and it provides **deterministic spatial grounding** — the coordinates that let the system draw a red box on the exact wrong line of the student's own photo (`step_checker._annotate`). A frontier vision model can say *what* the error is; it cannot reliably say *where* on the page it is. That verifiable "where" is what a teacher can trust and point at, and it is the part frontier models do not provide.

### Agentic vision loop

```
PERCEIVE   OpenCV segments N line boxes from the uploaded image
    |
    v
ACT        transcribe box_1 … box_N  (one vision call per box)
    |
    v
DECIDE     read unclear?  → re-crop the same box wider (pad 3 → 14 px), re-read
           still unclear? → skip that step and ask the student for a sharper photo
    |
    v
DECIDE     line repeats the one above? → skip it, a copied line is not an error
           (decided without a model call: `_same_line`)
    |
    v
ACT        check each step against the step above it (one call per transition)
    |
    v
DECIDE     first step that does not follow = the error line, tagged with a
           misconception category
    |
    v
ACT        draw the red box on that line of the student's photo; teach from there
```

Vision output directly changes what happens next: the number of downstream
tool calls is set by `findContours`, a low-confidence read triggers a wider
re-crop rather than a guess, and the located box decides where teaching starts.
Every decision is written to a `trace` returned with the result
(`core/vision/step_checker.py`, `check_working`), so the loop is inspectable.
This is the Agentic Vision Award criterion: perception influencing a subsequent
plan and tool call.

---

## 3. COOL Benchmark — Graviton vs x86

**Award target:** Best Use of COOL — Cloud-Optimized OpenCV Library on AWS Graviton.

We benchmarked EdKernel's actual OpenCV pipeline operations on two architectures using a reproducible synthetic worksheet image (1200×900 px, ruled lines, handwriting blobs, fixed seed).

### Setup

| | x86 baseline | Graviton (ARM) |
|---|---|---|
| Instance | Local dev (Arch Linux) | AWS t4g.small (ap-southeast-1) |
| Architecture | x86\_64 | aarch64 (Graviton2) |
| OpenCV | 5.0.0 | 5.0.0 |
| Python | 3.14 | 3.9 |
| Benchmark | 50 iterations per op (3 warm-up) | 50 iterations per op (3 warm-up) |

**Both runs use OpenCV 5.0.0** — the earlier version-mismatch caveat (5.0 vs 4.5)
is resolved, so this is a fair architecture comparison. Benchmark script:
`bench/graviton_standalone.py` (no external dependencies). Raw results:
`bench/results/x86.json`, `bench/results/graviton.json`.

### Results (OpenCV 5.0 on both)

| Operation | x86 (ms) | Graviton (ms) | Ratio |
|---|---:|---:|---:|
| resize | 0.25 | 0.37 | 1.5× slower |
| cvtColor | 0.19 | 0.33 | 1.8× slower |
| bilateralFilter | 21.63 | 27.48 | 1.3× slower |
| adaptiveThreshold | 5.82 | 8.13 | 1.4× slower |
| Canny | 1.28 | 2.15 | 1.7× slower |
| morphologyEx | 0.60 | 2.18 | 3.6× slower |
| findContours | 1.33 | 1.68 | 1.3× slower |
| **HoughLinesP** | **452.86** | **1736.59** | **3.8× slower** |
| warpPerspective | 2.61 | 5.19 | 2.0× slower |
| ink\_mask | 1.09 | 1.35 | 1.2× slower |
| segment pipeline | 1.97 | 4.15 | 2.1× slower |
| binarise (full) | 25.60 | 33.49 | 1.3× slower |

### Analysis

**Primary finding: `HoughLinesP` is the bottleneck on both, and catastrophic on
Graviton** — 1,737 ms per image (0.6 img/s), 3.8× the x86 cost and ~97% of the
naive pipeline's time on ARM. It is the clearest optimization target, and it
disproportionately punishes the cheaper hardware.

**With OpenCV 5.0 on both, x86 is faster on every operation (1.2–3.8×).** This
corrects an earlier, unfair result: a prior run showed Graviton "winning"
`findContours`, `ink_mask` and `binarise`, but that compared OpenCV 4.5 on ARM
against 5.0 on x86. On equal OpenCV 5.0, x86's SIMD advantage holds across the
board — the honest result, not the one we hoped for.

**The COOL win is not raw op speed — it is that the optimization makes the cheap
hardware viable.** Replacing `HoughLinesP` with the contour-based deskew (below)
removes ~1,737 ms from every image on Graviton, collapsing per-image pipeline
time from ~1.75 s to ~40 ms — roughly a **40× pipeline speedup on ARM**. Graviton
(t4g) runs ~20% cheaper per hour than the equivalent x86 (t3); once the bottleneck
is gone, the remaining pipeline is light enough that the cheaper ARM instance
becomes the cost-efficient choice for this CPU-bound CV workload.

### Action from findings — done, and re-measured

`HoughLinesP` was used only for deskew (estimating page rotation). **We replaced it**
with a contour-based estimator (`_contour_estimate` in `preprocess.py`): it takes
the min-area rectangle of each text-line blob from the *same* `findContours` output
the segmentation stage already computes, and reads the tilt off the longest box
edge. No second Hough pass.

Re-measured on this hardware, the op it removes vs the op it reuses:

| Op | Mean (ms) | Notes |
|---|---:|---|
| `HoughLinesP` (removed) | **445.9** | 2.2 img/s — 20× slower than the next op |
| `findContours` (reused) | **1.3** | already computed for segmentation |

Verified for correctness on the 9 labelled sample photos: the final deskew angle
(after the projection-profile refinement the seed feeds) matches the old
Hough-seeded result within **< 0.1° on 6 of 9** and **< 0.75° on 8 of 9**; one
outlier (v5) differs by 1.38°.

**Correction (found later, fixed).** Box counts were *not* fully unchanged: on v2
the new angle (1.10° vs 1.50°) let a fragment of the hand-drawn margin line
bridge two rows, and segmentation fell to 8/9 for a month before it was caught.
The root cause was the row merge, not the deskew — sweeping v2 through 0–1.5°
flipped the count with no pattern. The merge now also requires one blob's
vertical centre to sit inside the other, which restores **9/9** and raises
robustness under ±1° of extra rotation from 65/72 to 67/72 (the 5 remaining
failures are all one case, a crossed-out scribble). Net: the single heaviest OpenCV call is gone from the hot path
with no quality regression, and the replacement leans on `findContours` — an op
where Graviton *wins*.

---

## 4. Evaluation

### Check mode (MCQ / past-paper questions)

The system retrieves relevant curriculum chunks from ChromaDB, generates a multiple-choice question, and evaluates student answers.

- Correct answers: recorded to `users.db` via `/api/papers/correct`
- Wrong answers: hint ladder triggered; recorded on first wrong attempt
- Source attribution: PMT revision links shown below each RAG-sourced question

### Step checker (handwritten working)

Five-stage pipeline: rectify → binarise → segment → transcribe → evaluate.

**Measured accuracy (9 hand-labelled photos, `evals/vision.py`, Groq
`openai/gpt-oss-120b` + `qwen/qwen3.8-27b` vision, deterministic):**

| Metric | Score | What it measures |
|---|---|---|
| Segmentation (line count) | **9/9** | Pure OpenCV, no model — one box per written line |
| Step checker | **8/9 (89%)** | Names the exact wrong line (or "no error") |
| — error located | 3/3 | Found the wrong line on every error case |
| — clean pass | 5/6 | No false error on correct work |
| Transcription | **25/30 lines (83%)** | Faithful read of the handwriting |
| — clean reads | 5/9 | Whole problem read perfectly |
| Verdict given a faithful read | **5/5 (100%)** | Step-check logic, isolated from read errors |

Run of 23 Oct 2026, all nine cases scored (none lost to quota or `503`). Nine
photos from one student and one pen: this says "not obviously broken", not
"validated" — see Section 7.

**The headline finding: transcription is the bottleneck, not the reasoning.**
Scoring the read separately from the verdict shows that **when the handwriting is
transcribed faithfully, the step-check logic is correct every time (5/5)**. The
losses are all in the read (83%), not the logic. This drove the design: the
score climbed 44% → 71% → 86% (then 89% with all nine scored) as segmentation was fixed to
stop clipping crops and the transcription prompt was tightened to transcribe
verbatim (which also killed a dangerous failure mode — see below).

**Failure cases (honest reporting):**

| Case | What happened | Cause / status |
|---|---|---|
| v1 | `2x+7=19` read as `2x+2=10` | vision misread — the one remaining false positive; a read error, not a logic error |
| (fixed) v8 | previously read `x=4` as `x=-4` — **silently correcting the student's error** | fixed by the verbatim transcription prompt ("do NOT correct errors") |
| (fixed) v4 | previously flagged for an omitted `= 0` before factorising | fixed by a notation rule — formatting is not a method error |

**Path to improvement (in priority order):** (1) transcribe from the grayscale
crop, not the harsh binarised one — vision models read natural strokes far
better than adaptive-threshold output; (2) a strict "transcribe verbatim, do
not correct or solve" prompt to stop the v8 auto-correction; (3) a fine-tuned
handwriting-math vision model on collected real working — the real long-term
fix. The reasoning layer is already sound; the read is what needs the work.

### Classroom trial (23 Oct 2026)

Three secondary-school students used EdKernel for 17 minutes in a school computer lab,
on coordinate geometry (straight lines and circles). The server ran on a laptop
over the school network; every turn was logged. Full anonymised log:
`lab-chats-2026-10-23.md`.

| student | tutor turns | marked correct | marked wrong | quiz |
|---|---:|---:|---:|---|
| person 1 | 21 | 5 | 3 | 3/10 |
| person 3 | 13 | 1 | 0 | 4/10 |
| person 2 | 4 | 0 | 0 | — |

**Where it worked.** Person 1 got the distance between two points wrong, wrote
"im sorry", and stopped for two and a half minutes. The tutor named the distance
formula, gave an analogy, and asked only for the x and y gaps. The student
answered "6 and 8", then — without being asked to show working — "36 + 64 is
100 so it is 10!". Wrong → discouraged → scaffolded → solved it themselves,
with the answer never handed over. When the same student wrote "i dont think im
smart enough for this yet", the tutor acknowledged it and made the next step
smaller.

**Where it failed** (all listed in Section 7):
- Person 3 pasted questions and never attempted one. On a re-paste the tutor
  gave the full worked answer — six minutes of answer extraction.
- A correct partial answer (the x-coordinate of a midpoint) was marked wrong,
  and the student's correct protest was ignored.
- Person 2 was on a tablet; the on-screen keyboard covered the chat box, so
  they could not reply after their fourth turn. A layout bug, not
  disengagement — fixed afterwards (viewport sizing), not yet re-tested on a
  tablet.

**What this shows and does not show.** It shows real students using the tutor
and one clear case of scaffolded learning. It does **not** show learning gain:
there was no pre-test, N = 3, and the two quiz scores are post-test only.

### Teacher dashboard

Per-student progress is recorded to `users.db` on every MCQ answer (correct and wrong). The teacher panel at `/teacher` shows:
- Topic-level accuracy per student
- Activity over time
- **Class-wide misconception map**: when the step checker locates an error, the mistake is categorised and aggregated per topic, so a teacher sees *"N students made a sign error on rearranging"* — not just who scored low. This is the diagnostic layer no LMS ships, and it is *why* a school would install the tool.

**Reliability of the misconception categories (measured, honest).** The first
implementation classified errors by keyword-matching the examiner's free-text
explanation; tested against real explanations it scored **1/6 — the examiner
describes the correct step, never the error keyword**, so post-hoc matching fails.
The fix, verified at **7/7 (plus no false positive on a valid step)**: use
**coarse, non-overlapping buckets** (`sign` / `arithmetic` / `algebra_step` /
`other`) and have the examiner emit the tag **at decision time**, where it can
see the actual equations rather than guess from its own sentence — at zero extra
API cost. Coarse is deliberate: a wrong fine-grained label is worse than an
honest coarse one, and even a human would dispute the fine distinctions. The map
is presented to teachers as **AI-suggested and teacher-reviewed**, consistent
with the accuracy ceiling — a flag for review, not an authoritative grade.

---

## 5. Reproducibility

```bash
# Clone and run locally
git clone <repo>
cd EdKernel
cp .env.example .env   # fill in GROQ_API_KEY
pip install -r requirements.txt
python app.py

# Run COOL benchmark (requires OpenCV)
python bench/graviton_standalone.py --out bench/results/local.json

# Deploy to ECS (requires AWS credentials + ECR repo)
docker build -t edkernel .
docker tag edkernel <ecr-uri>
docker push <ecr-uri>
# update ECS service to force new deployment
```

Raw benchmark JSON: `bench/results/x86.json`, `bench/results/graviton.json`  
Benchmark script: `bench/graviton_standalone.py` — no EdKernel imports, runs on any machine with OpenCV and NumPy.

---

## 6. Sustainability & Scalability

EdKernel is efficient by design, not by accident. Two architectural choices —
running small models and doing the vision work in OpenCV on CPU — mean it uses a
fraction of the energy, water, and hardware of a frontier-model approach.

**Note on method.** Providers do not publish per-query energy or water, and
water use depends on each datacentre's cooling and location. The figures below
are order-of-magnitude estimates from published per-query ranges, stated with
their assumptions. They are meant as a relative comparison, not precise claims.

### Why the design saves

1. **Small models.** Inference runs on `openai/gpt-oss-20b/120b` and
   `qwen-27b`, not a frontier model with hundreds of billions of active
   parameters. Fewer FLOPs per token is the largest single lever.
2. **OpenCV offloads the vision work to CPU.** Rectify, deskew, binarise and
   segment run locally in milliseconds for negligible energy. A pure-LLM
   approach would feed the whole image to a large multimodal model and make it
   do everything on datacentre GPUs.
3. **Efficient inference hardware.** Groq's LPU is more energy-efficient per
   token than general-purpose GPUs.

Honest counterweight: the step checker makes *many small calls* (one
transcription per line, one check per transition). The savings come from
smaller models and the OpenCV offload — not from making fewer calls.

### Estimated per-task footprint (checking one photo of working)

| | Frontier multimodal (e.g. ChatGPT) | EdKernel (OpenCV + small Groq calls) |
|---|---|---|
| Electricity | ~1–5 Wh | ~0.2–1 Wh |
| Water (cooling + generation) | ~5–30 mL | ~1–6 mL |

→ roughly **3–5× less energy and water per task**.

Illustratively, a school of 500 students at 10 checks/day over a 180-day year
(~900,000 interactions) saving ~2.5 Wh and ~17 mL each is about **2,250 kWh**
(2–3 months of an average home's electricity) and **~15,000 L** of water saved
per year.

### Scalability — no owned AI hardware

The work splits across two tiers: EdKernel's own servers run the Flask app,
OpenCV pipeline and RAG retrieval; all LLM inference is offloaded to the
provider's API. EdKernel provisions **zero GPU/inference machines**.

For **1,000 students** (peak concurrency ~5–15%, so ~50–150 active at once),
most requests are I/O-bound — the app mostly waits on the inference API, with
short CPU bursts only during OpenCV preprocessing (~0.05–0.3 s per image, per
the COOL benchmark). Sizing:

- **~2–4 small CPU app servers** (ECS Fargate, 1 vCPU / 2 GB) behind the ALB
- **1 small RDS PostgreSQL** instance (replacing SQLite)
- RAG (951 chunks) fits in RAM — no dedicated store
- **0 GPU servers**

At that scale the binding constraint is not machine count but the inference
provider's **tokens-per-minute quota and cost**, which scale linearly with
usage. The takeaway: *1,000 students run on a handful of small CPU servers and
no owned AI hardware, because the heavy vision work is OpenCV on CPU and
inference is offloaded per call.*

---

## 7. Limitations and responsible use

**What it is not.** EdKernel is a practice tutor, not an assessor. Its verdicts
come from language models and are wrong some of the time (Section 4 gives the
measured rates), so it must never be used to grade students. The misconception
map is a prompt for a teacher to look, not a judgement.

**Known failure modes, seen with real students** (Section 4, classroom trial):
- The tutor can be argued into giving the full answer when a student re-pastes
  the same question instead of trying it.
- Partial answers are marked flatly wrong (a correct x-coordinate was marked
  `[WRONG]` and the student's protest ignored).
- It can lose track of which question the student is on.
- Handwriting reads fail on crossed-out work and very sparse writing; the step
  checker is only reliable on a flat photo of one problem.

**Data and privacy.** The app stores names, chat messages and quiz scores for
progress tracking. Guest mode needs only a display name — no email. Student
work is sent to a third-party inference API (Groq) to be read and checked;
schools should know this before using it. The trial log published in this
repo has names replaced with "person 1–3".

**Integrity.** Quiz answer keys stay on the server until an attempt is
submitted, so a student cannot read them from the page. The tab-switch counter
is a signal for the teacher, not proof of cheating — the trial showed it
over-counting on tablets (fixed, but still a heuristic).

**Fairness.** All evaluation photos come from one student and one pen, and the
trial had three students. Accuracy on other handwriting, other languages and
other devices is unmeasured.

## 8. What is still missing (honest)

- S3 for file storage (currently local disk on ECS)
- RDS PostgreSQL (currently SQLite on EFS: `users.db` and ChromaDB survive task restarts, but SQLite allows one writer at a time, which caps how far the app can scale out)
- Ingest does not run on container start; on a fresh EFS volume the RAG collection must be built once by hand
- AWS Bedrock LLM provider (account verification hold with AWS support)
- Misconception map is **built and live**, but categories are coarse and wobble on genuinely-ambiguous errors (e.g. subtracted-vs-added) — hence framed as teacher-reviewed, not authoritative. Full end-to-end verification through the *vision* path is still pending a window when the Groq vision model is not returning `503`.
- A pre-test: the classroom trial was post-test only, so it shows use, not learning gain
- Tutor fixes for the trial failures listed in Section 7
