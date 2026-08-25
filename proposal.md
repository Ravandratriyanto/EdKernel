# Metis — OpenCV AI Competition 2026 grant proposal

Fields below match the JotForm in the order the organisers list them.
Paste section by section.

---

## Team name

Metis

---

## Problem statement and intended real-world impact

A student stuck on a maths problem gets one bit of information back from
almost every tool available to them: right, or wrong. If it is wrong, they
are told to try again. They already knew that. What they do not know is
*where* it went wrong — whether the setup was fine and they dropped a sign
on line three, or whether the whole approach was doomed from the first line.

That is the difference between a grade and a teacher. A human tutor looking
at a sheet of handwritten working does not mark the final answer. They run a
finger down the page and stop at the first line that does not follow from
the one above it.

Metis does that. A student photographs or films their handwritten working.
OpenCV 5 finds the page, flattens it, cleans it, and cuts it into individual
working steps. Each step is checked against the step above it. The tutor
then says which line the error is on, and teaches from there.

The impact is access. One-to-one tutoring is the most effective
intervention in education and the least evenly distributed, because it is
priced by the hour of a human's attention. Per-step feedback on your own
handwriting is the part of tutoring that actually costs money to buy, and
it is the part no free tool currently does.

---

## Planned OpenCV 5 image and video analysis

OpenCV 5 owns everything between the camera and the reasoning model. It is
not a preprocessing courtesy — it decides how many model calls happen, what
each call contains, and what the unit of assessment is. Remove it and there
is no per-step checking, because there are no steps.

**1. Frame acquisition — `cv2.VideoCapture`**
Replaces a blind ffmpeg `fps=1/2` sample with in-process, content-aware
frame selection.

**2. Blur rejection — `cv2.Laplacian(gray, cv2.CV_64F).var()`**
Variance of the Laplacian as a sharpness score. Frames below threshold are
dropped before they cost anything. There is a recorded failure in the current
pipeline where a single motion-blurred frame returned 6,146 characters of
model monologue instead of a transcription; this stage is aimed directly at
it.

**3. Deduplication before inference — `cv2.ORB_create` + BFMatcher, with
`cv2.calcHist` / `cv2.compareHist` as the cheap first pass**
My current pipeline compares *transcribed text* with `difflib` at a 0.85
similarity threshold — which means every duplicate frame is paid for at full
inference cost before I discover it is a duplicate. Moving the comparison
to the pixels inverts that. (ORB and histogram comparison are in OpenCV
core; I avoid `img_hash`, which is contrib-only, so the COOL Marketplace
build is sufficient.)

**4. Page detection and rectification —
`cv2.cvtColor` → `cv2.GaussianBlur` → `cv2.Canny` → `cv2.findContours` →
`cv2.approxPolyDP` → `cv2.getPerspectiveTransform` → `cv2.warpPerspective`**
The classic four-point document scanner. Largest quadrilateral contour is
the page; the perspective transform flattens a phone photo taken at an angle
into a rectangular, deskewed image.

**5. Binarisation — `cv2.adaptiveThreshold` (adaptive Gaussian), with
`cv2.createCLAHE` for lamp glare**
Handles the uneven lighting of a real desk: a shadow across half the page,
a bright spot from an anglepoise.

**6. Step segmentation — `cv2.morphologyEx` with a wide horizontal kernel,
then `cv2.findContours`**
Dilating horizontally blobs each written line into a single connected
region; contouring those regions yields one bounding box per working step.
This is the stage the whole product rests on. The boxes define the unit of
assessment, they determine how many model calls are made and what is inside
each one, and their coordinates are what let the interface draw a rectangle
around line three on the student's own photograph.

To be precise about the division of labour: OpenCV finds, flattens, cleans
and cuts. Reading the mathematics inside each box is done by a vision-
language model. I am not claiming OpenCV performs OCR on equations.

---

## Planned AWS architecture and services

```
   student phone / browser
             |
             |  HTTPS
             v
   +---------------------------+
   |  Amazon CloudFront + S3   |   static front end
   +---------------------------+
             |
             v
   +---------------------------+
   |  Application Load Balancer|
   +---------------------------+
             |
             v
   +===========================+
   |  EC2  c8g (Graviton4)     |   <-- COOL AMI from AWS Marketplace
   |                           |
   |  OpenCV 5 vision service  |
   |   1 VideoCapture          |
   |   2 Laplacian blur reject |
   |   3 ORB dedupe            |
   |   4 warpPerspective       |
   |   5 adaptiveThreshold     |
   |   6 morphology -> boxes   |
   +===========================+
             |
             |  step crops + coordinates
             v
   +---------------------------+
   |  EC2  m7i (x86)           |   agent + tutor orchestration
   |  Flask app, session state |
   |  ChromaDB RAG grounding   |
   +---------------------------+
       |               |
       |               +--> Amazon S3   (frames, step crops, traces)
       |               +--> Amazon CloudWatch (per-stage latency, drop counts)
       |               +--> AWS Secrets Manager (API keys)
       v
   vision-language model  +  reasoning model
```

**Services:** EC2 (Graviton `c8g` for the COOL path, `m7i` for
orchestration), S3, CloudFront, Application Load Balancer, CloudWatch,
Secrets Manager, ECR for pinned container images.

**The x86 / Arm split is deliberate and documented.** The image and video
workload — every stage listed above — runs on Graviton under COOL. The
orchestration tier stays on x86 because it is bound by network I/O to model
endpoints, not by compute, and because it keeps the COOL benchmark clean:
the Arm instance runs the vision workload and nothing else, so a latency
measurement taken there is a measurement of OpenCV.

Both tiers ship as pinned containers from ECR so a judge can reproduce the
deployment from the repository.

---

## Target users and beneficiaries

Primary users are secondary-school students preparing for SAT and A-level
mathematics — specifically students without access to paid one-to-one
tutoring, who are currently working from mark schemes that show a final
answer and no route to it.

Secondary beneficiaries are teachers, who can photograph a set of scripts
and get a distribution of *where* a class went wrong rather than how many
got it right. A cohort that fails the same question for four different
reasons needs four different lessons, and that information does not exist in
a score.

---

## Proposed evaluation method and judge demonstration

This project already has a working evaluation harness, and I intend to
extend it rather than invent a demo. Current state, measured, not estimated:

- **50 held-out check-mode cases** (`evals/cases.jsonl`), scored
  automatically. Latest full run: **50/50 correct verdicts, 0/50 empty
  explanations.**
- **40 regression checks** (`evals/regress.py`) covering bugs already fixed
  once, run before every commit.
- **A learn-mode eval that currently scores 1/5** and which I report
  honestly as unresolved.

For the competition I add three vision-specific measurements:

1. **Step segmentation accuracy.** A hand-labelled set of photographed
   working, scored on whether each detected box contains exactly one working
   step. Reported with failure cases.
2. **Error localisation accuracy.** Scripts with a known error on a known
   line. The metric is whether the tutor names the correct line — a much
   harder and more useful number than final-answer accuracy.
3. **Inference calls saved.** Frames entering the pipeline versus frames
   reaching the model, before and after stages 2 and 3. This is the direct
   cost argument.

**COOL benchmark.** Identical container, identical inputs, run on Graviton
with COOL and on a stock OpenCV 5 baseline. I report per-stage latency and
throughput, with the deployment scripted so a judge can re-run it.

**Judge demonstration.** A live web endpoint. A judge photographs their own
handwritten working — with a deliberate mistake, at an angle, under bad
lighting — and watches the rectified page come back with boxes drawn on it
and one box flagged. The perception-to-action trace is displayed alongside,
so the causal chain from contour to decision is visible rather than
asserted. Plus the required video under five minutes.

---

## Path selection

**Both — COOL and Agentic Vision.**

**COOL.** The three operations AWS names as accelerated — resize, adaptive
Gaussian threshold, contour detection — are stages 4, 5 and 6 above. They
are my hot path, not a benchmark bolted on beside it. The core image
workload runs on Graviton under COOL, with the x86 orchestration tier
documented as the coexisting component.

**Agentic Vision.** The loop is genuinely closed:

```
  PERCEIVE   OpenCV: rectify, threshold, segment -> N step boxes
      |
      v
  DECIDE     agent inspects the boxes.
             quality too low?      -> re-run stage 4 with new parameters
             boxes look merged?    -> widen the morphology kernel, re-segment
             fewer boxes than
             expected?             -> request another frame from the video
             confident?            -> proceed
      |
      v
  ACT        transcribe box 1..N   (one tool call per box, count set by OpenCV)
      |
      v
  PERCEIVE   check each step against the step above it
      |
      v
  DECIDE     first step that does not follow = the error
             ambiguous?            -> ask the student to confirm the line
      |
      v
  ACT        teach from that line; draw the box on the student's photo
```

The OpenCV output does not merely get explained — it changes what happens
next. The number of downstream tool calls equals the number of contours
found. A low sharpness score triggers a re-capture request rather than a
transcription. Merged boxes cause the agent to adjust the morphology
parameters and re-run the OpenCV stage. That is perception influencing a
subsequent plan and tool call, which is the criterion.

---

## Technical feasibility

The tutor already exists and runs. **4,327 lines of Python** across a Flask
web front end and a CLI sharing one core: model client, ChromaDB RAG
grounding over real syllabus and past-paper material, image and video
handlers, a shared prompt layer with a verdict parser, and the eval harness
described above. Check mode scores 50/50 today.

What I build during the build phase is the OpenCV 5 vision front end and
the agent loop, deployed to AWS. I am not starting from a blank repository
and hoping the tutoring works — that part is measured. The risk in this
proposal is concentrated in one place, stage 6, and stage 6 is the part I am
most interested in getting right.

---

## Team bio

**Solo entrant.**

I am the only member of this team, and I built the system this proposal
describes. Rather than list skills, here is the evidence, all of it in the
repository:

**I finish things.** Metis is **4,327 lines of Python written over three
weeks** — 57 commits between 28 July and 17 August 2026, across 15 logged
working sessions. It is not a weekend spike. It runs today: two front ends
(a Flask web app and a CLI) over one shared core, with check mode scoring
50/50 on a held-out set.

**I plan before I build.** `readme.md` is a written build specification with
ten sequenced phases, each with its own definition of done — a spec to build
against, not documentation written afterwards. The phases were then built in
order, and the commit history is labelled by phase. Phases 1–7 are complete.

**I do not ship regressions twice.** `evals/regress.py` holds **40 automated
checks**, each one a bug that was found, fixed, and then locked down so it
cannot come back. They run before every commit.

**I record what is broken.** `devlog.md` carries **14 separate "Known issues"
sections** naming things that are still wrong in my own work — including a
learn-mode evaluation that currently scores 1/5, and a prompt string I have
changed three times where two of those changes made it worse. I would rather
have the honest number.

**I understand the layer below the API.** `training/train_tiny.py` is a
complete GPT — tokenizer, model, training loop, sampling — in 333 lines,
written from scratch without `transformers`. I did that so the models I call
would stop being magic.

**On complementary skills.** Solo means the whole stack sits in one head:
computer vision, retrieval (ChromaDB over ~3,500 chunks of real syllabus
material), web and CLI front ends, evaluation methodology, model internals,
and deployment hygiene — API keys isolated in a gitignored `.env` behind a
pre-commit hook that blocks key patterns from ever entering a commit. There
is no integration risk between components because there is no seam between
authors.


---

## Sources

- https://opencv26.devpost.com/
- https://opencv.org/opencv-ai-competition-2026/
