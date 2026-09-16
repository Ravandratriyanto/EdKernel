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

Reading handwritten maths is no longer a differentiator — frontier multimodal models do it. EdKernel's defensible value is the combination a general chatbot does not ship: **per-step, method-mark-style checking, grounded in a specific exam board or national curriculum, that withholds the answer** (teaches rather than solves), **surfaces misconceptions to teachers**, and is delivered as a **kernel any region builds its own UI on**. A student pasting working into ChatGPT gets the answer handed over — curriculum-blind, and counter-productive for learning.

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

Every uploaded image passes through six stages before any model call is made:

| Stage | OpenCV call | Purpose |
|---|---|---|
| 1. Blur rejection | `cv2.Laplacian(gray, cv2.CV_64F).var()` | Drop frames below sharpness threshold before paying inference cost |
| 2. Rectification | `findContours` → `approxPolyDP` → `getPerspectiveTransform` → `warpPerspective` | Find the page quad, flatten a phone photo taken at an angle |
| 3. Binarisation | `bilateralFilter` → `adaptiveThreshold` (Gaussian) | Handle uneven desk lighting; isolate ink from background |
| 4. Deskew | `HoughLinesP` on ink mask → rotation estimate → `warpAffine` | Correct rotated pages |
| 5. Step segmentation | `morphologyEx` (horizontal close) → `findContours` | One bounding box per working line |
| 6. Ink mask | `threshold` (Otsu) | Feed HoughLinesP with a clean binary |

The output is a list of bounding boxes. The number of model calls made downstream equals the number of boxes returned. OpenCV does not merely preprocess — it decides the shape of inference.

### Agentic vision loop

```
PERCEIVE   OpenCV segments N step boxes from uploaded image
    |
    v
DECIDE     quality check: sharpness score, box count plausible?
           merged boxes? → widen morphology kernel, re-segment
           too few boxes? → request another photo
    |
    v
ACT        transcribe box_1 … box_N  (one tool call per box)
    |
    v
PERCEIVE   check each step against the step above it
    |
    v
DECIDE     first step that does not follow = the error line
    |
    v
ACT        teach from that line; draw bounding box on student's photo
```

Vision output directly changes what happens next. A low sharpness score triggers re-capture, not transcription. Merged boxes cause the agent to adjust morphology parameters and re-run. The number of downstream tool calls is set by `findContours`. This is the Agentic Vision Award criterion: perception influencing a subsequent plan and tool call.

---

## 3. COOL Benchmark — Graviton vs x86

**Award target:** Best Use of COOL — Cloud-Optimized OpenCV Library on AWS Graviton.

We benchmarked EdKernel's actual OpenCV pipeline operations on two architectures using a reproducible synthetic worksheet image (1200×900 px, ruled lines, handwriting blobs, fixed seed).

### Setup

| | x86 baseline | Graviton (ARM) |
|---|---|---|
| Instance | Local dev (Arch Linux) | AWS t4g.micro (ap-southeast-1) |
| Architecture | x86\_64 | aarch64 |
| OpenCV | 5.0.0.93 | 4.5.4 |
| Python | 3.14 | 3.10.12 |
| Benchmark | 50 iterations per op (3 warm-up) | 50 iterations per op (3 warm-up) |

Benchmark script: `bench/graviton_standalone.py` (no external dependencies). Raw results: `bench/results/x86.json`, `bench/results/graviton.json`.

### Results

| Operation | x86 (ms) | Graviton (ms) | Ratio | Notes |
|---|---:|---:|---:|---|
| resize | 0.26 | 0.59 | 2.3× slower | SIMD gap, OpenCV 5 vs 4 |
| cvtColor | 0.29 | 0.87 | 3.0× slower | |
| bilateralFilter | 33.00 | 38.53 | 1.2× slower | Both slow; compute-bound |
| adaptiveThreshold | 8.32 | 9.03 | 1.1× slower | Effectively equal |
| Canny | 1.89 | 2.36 | 1.3× slower | |
| morphologyEx | 0.80 | 1.84 | 2.3× slower | |
| **findContours** | **1.77** | **1.39** | **0.8× — Graviton wins** | ARM NEON benefits pointer-chasing |
| HoughLinesP | 240.09 | 1587.23 | 6.6× slower | Pipeline bottleneck on both |
| warpPerspective | 2.56 | 17.81 | 7.0× slower | Major OpenCV 5 SIMD rewrite |
| ink\_mask | 4.58 | 1.83 | 0.4× — Graviton wins | Otsu threshold; ARM NEON |
| segment pipeline | 2.68 | 3.42 | 1.3× slower | |
| binarise (full) | 295.66 | 48.96 | 0.2× — Graviton wins | Different input path |

### Analysis

**Primary finding: `HoughLinesP` is the bottleneck on both architectures.** On x86 it costs 240 ms per image (81% of total pipeline time). On Graviton t4g.micro it costs 1,587 ms — 6.6× worse. This is our clearest optimization target.

**Where Graviton wins:** `findContours` (1.3×) and `ink_mask` (2.5×) run faster on ARM. Both are memory-traversal workloads that benefit from ARM NEON's memory bandwidth characteristics. The segment pipeline, which chains morphology → findContours, is within 1.3× of x86.

**Key caveat:** The two runs use different OpenCV versions (5.0 x86 vs 4.5 Graviton) and different instance classes. OpenCV 5 introduced significant SIMD rewrites for `warpPerspective` and `resize` on x86; those gains do not exist in 4.5 on ARM. A fair comparison requires OpenCV 5 on both — which is the production target.

### Action from findings

`HoughLinesP` is used only for deskew (estimating page rotation). We are replacing it with a contour-based rotation estimator that uses the same `findContours` output already computed in the segmentation stage — an operation where Graviton wins. This eliminates the bottleneck and plays to Graviton's strength.

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
| Step checker (scored cases) | **6/7 (86%)** | Names the exact wrong line (or "no error") |
| — error located | 1/1 | Found the wrong line on error cases |
| — clean pass | 5/6 | No false error on correct work |
| Transcription | **20/24 lines (83%)** | Faithful read of the handwriting |
| — clean reads | 4/7 | Whole problem read perfectly |
| Verdict given a faithful read | **4/4 (100%)** | Step-check logic, isolated from read errors |

Two of the nine (the hardest — crossed-out scribbles, repeated lines) were not
scored: the Groq vision model returned `503 over capacity` on those requests
during the run.

**The headline finding: transcription is the bottleneck, not the reasoning.**
Scoring the read separately from the verdict shows that **when the handwriting is
transcribed faithfully, the step-check logic is correct every time (4/4)**. The
losses are all in the read (83%), not the logic. This drove the design: the
score climbed 44% → 71% → 86% across the session as segmentation was fixed to
stop clipping crops and the transcription prompt was tightened to transcribe
verbatim (which also killed a dangerous failure mode — see below).

**Failure cases (honest reporting):**

| Case | What happened | Cause / status |
|---|---|---|
| v1 | `2x+7=19` read as `2x+2=10` | vision misread — the one remaining false positive; a read error, not a logic error |
| v7, v8 | not scored | Groq `503` — vision model over capacity during the run |
| (fixed) v8 | previously read `x=4` as `x=-4` — **silently correcting the student's error** | fixed by the verbatim transcription prompt ("do NOT correct errors") |
| (fixed) v4 | previously flagged for an omitted `= 0` before factorising | fixed by a notation rule — formatting is not a method error |

**Path to improvement (in priority order):** (1) transcribe from the grayscale
crop, not the harsh binarised one — vision models read natural strokes far
better than adaptive-threshold output; (2) a strict "transcribe verbatim, do
not correct or solve" prompt to stop the v8 auto-correction; (3) a fine-tuned
handwriting-math vision model on collected real working — the real long-term
fix. The reasoning layer is already sound; the read is what needs the work.

### Teacher dashboard

Per-student progress is recorded to `users.db` on every MCQ answer (correct and wrong). The teacher panel at `/teacher` shows:
- Topic-level accuracy per student
- Activity over time
- (Planned) misconception tags: why the student was wrong, not just that they were wrong

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

## 7. What is still missing (honest)

- `HoughLinesP` → contour-based deskew replacement (planned, not built)
- OpenCV 5 on Graviton for a fair COOL comparison (blocked on instance setup)
- S3 for file storage (currently local disk on ECS)
- RDS PostgreSQL (currently SQLite, not durable across ECS restarts)
- AWS Bedrock LLM provider (account verification hold with AWS support)
- Misconception detection (architecture designed, not implemented)
- Architecture diagram (required deliverable)
- Demo video (required deliverable, due 26 Oct 2026)
