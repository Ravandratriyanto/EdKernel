# EdKernel — demo video script (target 4:30, hard limit 5:00)

Rules this has to meet: shows **the team**, **the app working**, **the architecture**,
**the principal results**. Upload as **unlisted** YouTube.

Spoken words ≈ 620 → about 4:25 at a normal pace. Record each scene as its own
clip, then join them. Say the lines in your own words — the numbers must stay exact.

---

## Before you record (10 min)

- [ ] Start the app locally (`python app.py` or `start-lab.sh`), log in, class = **Math**.
- [ ] Do one test run of the photo checker on `evals/vision_samples/v8.jpg` — it
      uses Groq quota, and a 503 mid-take wastes the take. If Groq is slow, record
      the result screen once and reuse it.
- [ ] Open in tabs: `lab-chats-2026-10-23.md` (scroll to line ~60),
      `docs/architecture.png`, `report.md` results table, AWS console → ECS →
      `edkernel-service` (shows Running), EC2 → Load balancers.
- [ ] Close anything showing student names, `.env`, API keys, or your email.
- [ ] Browser zoom 125% so text is readable at 1080p.

---

## Scene 1 — Who (0:00–0:20) · camera on you

> Hi, I'm [name], and I built EdKernel on my own for the OpenCV AI Competition.
> EdKernel is a maths tutor that looks at a photo of your handwritten working and
> finds the exact line where it went wrong — then helps you fix it without
> giving you the answer.

## Scene 2 — The problem (0:20–0:45) · photo of v8 on screen

> When a student gets a maths question wrong, most apps just say "wrong", or show
> the full solution. Neither helps. A teacher would point at the line where the
> mistake happened and ask a question. That's what I wanted to automate.

## Scene 3 — Live demo: photo → error line (0:45–2:00) · screen recording

Upload `v8.jpg`. While it runs:

> This is a real photo, taken on a phone. First, OpenCV does the parts that need
> to be exact. It looks for the page edges and straightens the page — or, if it
> can't find a clean page, it measures the tilt of the writing and rotates it.
> Then it turns the image black and white, and smears the ink sideways so each
> written line becomes one blob. Those blobs become line boxes.

Result appears — point at the boxes, then the red box:

> Each line is cropped, enlarged, and read by a vision model. Then each step is
> checked against the step above it. Here, line 3 doesn't follow from line 2 —
> so it's boxed in red, with the reason.

Open the **trace**:

> This is the agent's trace. It's not a fixed script: if a line comes back
> unclear, it re-crops wider and reads it again, and if it's still unclear it
> asks the student for a sharper photo. If a student just copied a line out
> again, it skips it instead of calling it an error. The OpenCV output decides
> what the agent does next.

## Scene 4 — Real students (2:00–2:50) · `lab-chats-2026-10-23.md`

> Today I ran it in a school computer lab with three students for 17 minutes.
> Here's one exchange. The student got a distance question wrong and typed
> "im sorry" — then stopped for two and a half minutes.

Scroll to "6 and 8" and "36 + 64 is 100 so it is 10!":

> The tutor didn't give the answer. It named the idea, and asked only for the
> gaps in x and y. The student said "6 and 8" — then, without being asked:
> "36 plus 64 is 100, so it is 10!" That's the moment I built this for.

## Scene 5 — Teacher view (2:50–3:10) · teacher page / misconception map

> Every flagged error is tagged with a type of mistake — sign error, wrong
> operation, and so on — so a teacher sees what the class gets wrong, not just
> who got it wrong.

## Scene 6 — Architecture (3:10–3:45) · `docs/architecture.png`, then AWS console

> It runs on AWS. A load balancer sends traffic to a Flask app on ECS Fargate.
> The OpenCV pipeline runs inside that container on the CPU — no GPU needed.
> Accounts, logs and the curriculum search index sit on EFS, so they survive a
> restart. The image is built from the repo and stored in ECR. The language and
> vision models are called through Groq.

Switch to the ECS console showing the service running (2 seconds is enough).

## Scene 7 — Results, honestly (3:45–4:20) · `report.md` results table

> On my nine test photos: the OpenCV line-finding got all nine right. The step
> checker gave the right verdict on eight of nine, and found the exact wrong
> line in all three photos that had an error. Its one miss was a misread —
> whenever a line was read correctly, the verdict was right, five out of five.
>
> What didn't work: one student pasted questions and on a re-paste the tutor
> gave the full answer. A correct partial answer was once marked wrong. And three
> students isn't a study — there was no pre-test. All of that is in the report.

## Scene 8 — Close (4:20–4:35) · camera on you

> Next is a proper before-and-after study and fixing the tutor's answer leaks.
> The code, the report and the live link are in the submission. Thanks for
> watching.

---

## Don't say

- "kernel" as in an OS kernel — say **engine**.
- That OpenCV reads handwriting better than AI models — it doesn't; it gives
  exact, repeatable line positions.
- Anything about Graviton being faster — it was slower on every op we timed.
- That it's been validated with students — it's one 17-minute session, N=3.
