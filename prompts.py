"""The bits of prompting that both front ends share.

app.py and main.py have drifted apart three times. Anything they both send
belongs here, so a change lands in both or in neither.

The [CORRECT]/[WRONG] convention lives here too — the instruction that asks for
it and the parser that reads it, side by side, because they only make sense as
a pair.
"""

import re

# The verdict marker. Anchored to end-of-string, so it must be the last thing
# in the reply — that is why the instruction below says to write nothing after
# it. Change one of these two and you must change the other.
_SIGNAL_RE = re.compile(r'\s*\[(CORRECT|WRONG)\]\s*$', re.IGNORECASE)

# Models mimic the bracket convention they see — the [CORRECT]/[WRONG] signal and
# the [Tutor note: ...] lines we inject — and invent markers of their own, e.g.
# [WAITING FOR RESPONSE]. Anchored to a whole line so it can't eat interval
# notation like [0, 5] or a citation mid-sentence.
_STRAY_MARKER_RE = re.compile(r'^[ \t]*\[[A-Z][A-Z0-9 _:-]{2,40}\][ \t]*$\n?', re.MULTILINE)

CHECK_SIGNAL = (
    "Finish your reply with a last line that is exactly [CORRECT] or exactly "
    "[WRONG]. Keep the square brackets — a bare word without them does not "
    "count. Write nothing after that line."
)
# Do not add "that line judges the student, not your explanation" here. It was
# tried on 2026-08-09 and backfired: it biased the model toward [WRONG], and
# "accepts correct" fell from 15/15 to 12/15 — it started marking answers wrong
# straight after explaining they were right. The wording above scored 28/30 on
# two consecutive runs. Re-measure with `python -m evals.run` before changing it.


def build_check_prompt(question: str, answer: str,
                       context_prefix: str = "", note: str = "") -> str:
    """The check-mode prompt, identical in the web app, the CLI and the evals.

    Before this existed the web app's text path sent no verdict instruction at
    all, so `strip_signal` found nothing and check mode returned prose with no
    machine-readable answer. Measured over 30 eval cases: 0 of 30 replies
    carried a signal.
    """
    return (f"{context_prefix}"
            f"Question: {question}\n"
            f"Student's answer: {answer}\n\n"
            f"{note}"
            "Is the student's answer correct? Explain briefly.\n"
            f"{CHECK_SIGNAL}")


def strip_signal(text: str) -> tuple:
    """Split a reply into (text to show, True/False/None verdict).

    None means the model did not signal — treat that as "do not know", never
    as wrong.
    """
    m = _SIGNAL_RE.search(text)
    if m:
        clean, correct = text[:m.start()], m.group(1).upper() == "CORRECT"
    else:
        clean, correct = text, None
    clean = _STRAY_MARKER_RE.sub('', clean)
    return re.sub(r'\n{3,}', '\n\n', clean).strip(), correct
