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

# The "Check: correct answer is X; student wrote Y" line that CHECK_SIGNAL asks
# for is scaffolding for the model, not something to show. Matched on the full
# instructed form rather than a bare "Check:", so an ordinary tutor line like
# "Check: does that make sense?" is left alone.
_CHECK_LINE_RE = re.compile(r'^[ \t]*Check:\s*correct answer is\b[^\n]*\n?',
                            re.MULTILINE | re.IGNORECASE)

CHECK_SIGNAL = (
    "Just before your last line, write one line in exactly this form:\n"
    "Check: correct answer is <your answer>; student wrote <their answer>.\n"
    "They match if they mean the same thing mathematically, even when written "
    "differently: 3n + 2 is the same as 2 + 3n, 0.5 is the same as 1/2, and "
    "x = 7 or x = -7 is the same as x = +/-7. Only the value matters, never the "
    "wording or the order.\n"
    "Then finish with a last line that is exactly [CORRECT] if those two match, "
    "or exactly [WRONG] if they do not. Keep the square brackets — a bare word "
    "without them does not count. Write nothing after that line."
)
# Measured 2026-08-12 on the 50-case set: 50/50, every verdict from the signal.
# The previous wording — the marker instruction alone, no Check: line — scored
# 49/50. Treat one case as noise; what this actually buys is below.
#
# The Check: line is scaffolding. `_CHECK_LINE_RE` strips it before the reply
# reaches a student, so changing its wording means changing that regex too.
#
# Two earlier attempts failed and are recorded so they are not retried blind:
#
# 1. "that line judges the student, not your explanation" (2026-08-09) biased
#    the model toward [WRONG]. "accepts correct" fell 15/15 -> 12/15: it marked
#    answers wrong straight after explaining they were right.
# 2. The Check: line WITHOUT the equivalence sentence (2026-08-10) made the
#    model compare the two answers as *text*. It wrote "correct answer is
#    2 + 3n; student wrote 3n + 2" and marked it [WRONG]. Systematic, not
#    random — it failed any correct answer written in a different order.
#
# The equivalence sentence is the part that fixes (2), and that — not the extra
# point — is the evidence for this wording: 25/25 on correct answers, with the
# text-comparison failure absent from all of them.
#
# Both attempts, and this one, aim at the same defect: the marker coming loose
# from the reasoning. 50/50 is one clean run, not proof it is gone.


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


# What to say when the model sent a verdict and nothing else. Short, plain, and
# ending in a question, so the lesson keeps its shape.
_EMPTY_REPLY = {
    # Learn mode: end on a question, so the lesson keeps its shape.
    True:  {True: "That's right. Ready for the next step?", False: "That's right."},
    False: {True: "Not quite. Want to try that again?",     False: "Not quite."},
    None:  {True: "Can you say a bit more about that?",
            False: "I could not tell from that. Can you show your working?"},
}


def tutor_reply(raw: str, teaching: bool = True) -> tuple:
    """strip_signal for the teaching paths, which must never return nothing.

    Seen live on 2026-08-10: the student answered "is x = 5" correctly and the
    model replied with the bare marker and no words. Stripping the marker left
    an empty string, the web app rendered an empty speech bubble, and the empty
    string was appended to `messages` as the assistant turn — so the history
    sent back on the next turn had a blank tutor message in it.

    The prompt now tells the model not to do this. This is the safety net for
    when it does anyway, because a canned sentence is recoverable and a blank
    bubble is not.

    `teaching` picks the wording: learn mode ends on a question to keep the
    lesson moving, check mode does not, because there is no next step there.
    """
    text, correct = strip_signal(raw)
    return (text or _EMPTY_REPLY[correct][teaching]), correct


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
    clean = _CHECK_LINE_RE.sub('', clean)
    return re.sub(r'\n{3,}', '\n\n', clean).strip(), correct
