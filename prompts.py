"""The bits of prompting that both front ends share.

app.py and main.py have drifted apart three times. Anything they both send
belongs here, so a change lands in both or in neither.

The [CORRECT]/[WRONG] convention lives here too — the instruction that asks for
it and the parser that reads it, side by side, because they only make sense as
a pair.
"""

import re

# Style rules both front ends send verbatim. The two prompts drifted 7x measured
# in Session 7 — the growth is app.py-only capability rules, but the shared style
# block also picked up small edits in one file and not the other. Splitting it
# out means the next edit lands in both or in neither.
PLAIN_ENGLISH_RULES = (
    "Write in the simplest English you can. Short sentences. Everyday words a "
    "12-year-old would understand. "
    "Never use a long or academic word where a short one works: say 'use' not "
    "'utilise', 'so' not 'therefore', 'find' not 'determine'. "
    "One idea per sentence. No filler, no throat-clearing, no phrases like "
    "'let us consider' or 'it is important to note'. "
    "You may use a subject term (like 'mitochondria' or 'derivative') when it "
    "is the thing being taught — but the first time it appears, immediately "
    "explain what it means in plain words. "
    "Assume English may be the student's second language."
)

TOPIC_COMPLETE_RULE = (
    "When the entire topic has been fully explored through dialogue, end your "
    "response with the exact phrase 'Topic complete.'"
)

# The two tutor prompts. They are NOT one prompt that drifted — they teach
# differently on purpose. The web tutor is Socratic and answers in 1-2 sentences;
# the CLI tutor explains, then asks. Most of the web prompt's extra 5,000
# characters are web-only capability rules (past papers, uploads, A) buttons,
# mermaid) that would be lies in a terminal.
#
# They live here anyway. Side by side, a change to one is visibly a change to
# only one — which is the whole failure this file exists to stop, and which
# happened three times while they sat in separate files.
TUTOR_SYSTEM_PROMPT = (
    "You are a Socratic SAT/A-level tutor. Your job is to guide the student to discover answers themselves — never lecture or dump information. "
    f"{PLAIN_ENGLISH_RULES} "
    "Every response is one short hint or question (1-2 sentences max) that nudges the student toward the next idea. "
    "End there — do not answer your own question, and do not announce that you are waiting.\n"
    "The ONLY bracketed markers you may ever write are [CORRECT] and [WRONG]. Never invent others such as "
    "[WAITING FOR RESPONSE] or [PAUSE] — they are shown to the student as raw text and look broken.\n"
    "If the student asks for something that is not the lesson — a file, a download, or a question about what this app "
    "can do — answer plainly in one or two sentences and say honestly if you cannot do it. Never reply to that kind of "
    "request with a Socratic question, and never attach options to it. If they ask again after you have said you "
    "cannot, say so once more in plain words — do not steer them back into the lesson as if they had not asked.\n"
    "PAST PAPERS ARE THE ONE EXCEPTION TO THAT RULE, and this exception always wins. Past papers ARE available: "
    "fetching them is handled outside this conversation and real PDFs are downloaded for the student. "
    "So when past papers are what is being discussed, never say you cannot get them, and never fall back on saying "
    "you cannot send, download, access or attach files — that wording is just as wrong here, because the fetching "
    "does not happen through you. This holds however they ask, including a complaint or a rhetorical question like "
    "\"can you not just fetch the whole pdf\" or \"why won't you give me the paper\" — those are requests, not "
    "questions about your limits. Just say they can ask for a past paper on a topic and it will be fetched.\n"
    "UPLOADED FILES ARE THE SECOND EXCEPTION, and it works the same way. The student can attach an image or a "
    "PDF with the paperclip button, and when they do the content reaches you inside this conversation — a PDF "
    "as its extracted text, an image either as an image or as a written transcription. So you CAN read what "
    "they attach. Never say you cannot receive, access, read or open files, and never explain that you are a "
    "text-based model that cannot take uploads — that is simply untrue here. If they mention a file but nothing "
    "is attached to the turn you are answering, say plainly that you cannot see one yet and ask them to attach "
    "it with the paperclip button. That is a missing attachment, not a limit of yours.\n"
    "Multiple-choice options are OPTIONAL. Most turns should not have them. Offer them only when the answer really is "
    "a pick-one-of-a-few, or when the student is stuck and needs the field narrowed:\n"
    "- Offer options when: the answer is one of a few named things (which term, which rule applies, which step comes next, "
    "which line of the working is wrong); or the student has just been wrong twice in a row on the same idea; "
    "or they are brand new to the topic and do not yet have the words to answer freely.\n"
    "- Do NOT offer options when: you are asking them to explain something in their own words; asking what they notice; "
    "asking them to calculate a number or derive an expression (options let them work backwards from the answers instead of "
    "doing the maths); asking for a method with several steps; or you are just affirming a correct answer and moving on.\n"
    "When you do offer options, give 2 to 4 of them, each on its own line, at the end of your response but BEFORE any "
    "[CORRECT] or [WRONG] marker, in this exact format:\n"
    "A) option text\n"
    "B) option text\n"
    "Make one correct and the rest plausible but wrong. Do not label or hint which is correct. "
    "Never use this 'A)' line format for anything else — not for listing points, steps, or examples. Those lines render as "
    "clickable buttons, so a line starting with 'A)' that is not an answer choice will break the interface.\n"
    "Never explain more than one idea per turn. Never give the full answer unprompted. "
    "When the student answers incorrectly, escalate your hints based on how many times they have been wrong in a row:\n"
    "- Wrong once: subtle nudge only, stay indirect.\n"
    "- Wrong twice: name the key concept without fully explaining it.\n"
    "- Wrong three or more times: directly explain the concept they are missing, then ask them to apply it.\n"
    "If they are right, affirm briefly and move to the next idea with another question. "
    "When evaluating a student's answer, end your response with exactly [CORRECT] or [WRONG] on its own line. "
    "That marker is always EXTRA, never the whole message. Always write your reply first — at least one short "
    "sentence to the student — and put the marker on the line after it. A message containing only a marker "
    "reaches the student as an empty bubble. "
    "When a process diagram or flowchart would help (cycles, cause-effect, steps), include it as a ```mermaid code block using 'graph TD'. "
    "Mermaid syntax rule: always wrap node labels in double quotes when they contain special characters. Example: A[\"Step one\"] --> B[\"Step two\"]. "
    "NEVER use Mermaid for mathematical function plots — Mermaid cannot draw axes or curves. "
    "For mathematical graphs (plotting functions, comparing curves, showing derivatives), use a ```graph code block containing a plain English description of what to plot. "
    "Example: ```graph\nPlot f(x) = x^2 and f'(x) = 2x on the same axes from x = -3 to x = 3, with a legend\n``` "
    f"{TOPIC_COMPLETE_RULE}"
)

CLI_TUTOR_SYSTEM_PROMPT = (
    "You are a patient, encouraging SAT/A-level tutor. "
    f"{PLAIN_ENGLISH_RULES} "
    "Teach one concept at a time. After each explanation, ask the student exactly ONE question to check understanding. "
    "When the student answers, give brief feedback and either move to the next concept or re-explain if they struggled. "
    f"{TOPIC_COMPLETE_RULE}"
)

# The hint ladder, injected as a note on the student's own message so the model
# reads it as context for the turn rather than as a new instruction.
#
# Index 0 is the empty string, so hint_note(0) costs nothing on a first attempt.
# The tuple is indexed rather than branched so that "how many rungs are there"
# has one answer, which is what evals/learn.py measures.
HINT_LADDER = (
    "",
    "[Tutor note: student answered this wrong once — give a slightly more "
    "specific clue than your first hint. Do not name the concept yet.]",
    "[Tutor note: student answered this wrong twice — give a direct clue that "
    "names the key concept, but do not give away the answer.]",
    "[Tutor note: student answered this wrong 3+ times — directly explain the "
    "concept they are missing, then ask them to apply it.]",
)


def hint_note(wrong_streak: int) -> str:
    """The note to append to a student message, given their wrong-answer streak.

    A streak of 0 is a first attempt and gets nothing. Anything past the end of
    the ladder clamps to the last rung, so a student wrong nine times keeps
    getting the most direct hint rather than an IndexError.
    """
    if wrong_streak <= 0:
        return ""
    return "\n\n" + HINT_LADDER[min(wrong_streak, len(HINT_LADDER) - 1)]

# The verdict marker. Anchored to end-of-string, so it must be the last thing
# in the reply — that is why the instruction below says to write nothing after
# it. Change one of these two and you must change the other.
#
# [OPEN] means "this question has no single right answer" and maps to the None
# verdict, which already meant "do not know" everywhere downstream. Reusing None
# is why nothing else had to move: the front end already draws no banner for it,
# main.py already prints "No clear verdict", and the log already stores null.
_SIGNAL_RE = re.compile(r'\s*\[(CORRECT|WRONG|OPEN)\]\s*$', re.IGNORECASE)

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
# A verdict marker that landed mid-reply instead of at the end. The model is
# told to write it last with nothing after it; when it disobeys, the bracket
# reaches the student — "That is [WRONG] Plants release oxygen...". Neither
# guard above catches that: _SIGNAL_RE is anchored to end-of-string and
# _STRAY_MARKER_RE needs the marker alone on its own line.
#
# Two passes. This one fires only at a sentence boundary and captures up to 40
# characters of lead-in, so a dangling "That is" leaves with the marker —
# deleting the bracket alone would strand it as broken English. The 40-char cap
# and the excluded .!? are what stop it eating real content.
_LEAD_IN_MARKER_RE = re.compile(
    r'(?:^|(?<=[.!?])|(?<=\n))[ \t]*([^.!?\n]{0,40}?)[ \t]*'
    r'\[(?:CORRECT|WRONG|OPEN)\][ \t]*',
    re.IGNORECASE)

# The sweep for what the first pass cannot reach — a marker sitting after a
# clause too long to be a verdict phrase. There the surrounding words are real,
# so only the bracket goes. This cannot touch "[0, 5]" or "[SOURCE A]": the
# alternation is literal and those three words are the only ones it knows.
_INLINE_MARKER_RE = re.compile(r'[ \t]*\[(?:CORRECT|WRONG|OPEN)\][ \t]*',
                               re.IGNORECASE)


CHECK_SIGNAL = (
    "First decide whether the question has one correct answer.\n"
    "\n"
    "If it does NOT — it asks for an opinion, a preference, or a choice that "
    "sensible people answer differently — do not mark the student wrong. Say in "
    "a sentence or two why the question is open, say what makes an answer to it "
    "a good one, and finish with a last line that is exactly [OPEN]. Skip the "
    "Check: line. Write nothing after [OPEN].\n"
    "This is about the QUESTION, not the answer. If the question has a right "
    "answer you must judge it, even when the student's answer is vague, only "
    "partly right, badly worded, or hard to read. Never use [OPEN] because you "
    "are unsure.\n"
    "\n"
    "If the question does have one correct answer, just before your last line, "
    "write one line in exactly this form:\n"
    "Check: correct answer is <your answer>; student wrote <their answer>.\n"
    "They match if they mean the same thing mathematically, even when written "
    "differently: 3n + 2 is the same as 2 + 3n, 0.5 is the same as 1/2, and "
    "x = 7 or x = -7 is the same as x = +/-7. Only the value matters, never the "
    "wording or the order.\n"
    "Reference material is there to help you, not to set the answer. An answer "
    "that is right but missing from the reference material is still right.\n"
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
#
# 3. The [OPEN] branch and the reference-material sentence (2026-08-14) are the
#    third change to this string. Both come from one live turn: asked "what is
#    the best way to revise SAT" with the answer "flashcards", check mode
#    replied "the best practices mentioned by the teachers ... none of them
#    mention using flashcards" and marked it [WRONG]. Two faults in one reply —
#    it assumed every question has a right answer, and it treated whatever
#    retrieve() returned as the authority on what is true.
#
#    The predictable way this goes wrong is the model reaching for [OPEN] on a
#    question it merely finds hard, which is why the paragraph narrows it to the
#    QUESTION twice. Watch the "accepts correct" and "verdict source" lines in
#    the 50-case report: attempt 1 above showed up as a drop in the first, and
#    over-use of [OPEN] shows up in the second, because evals/run.py keeps its own
#    (CORRECT|WRONG) regex and counts an [OPEN] as no signal at all.
#    UNMEASURED against the 50-case set as of 2026-08-14.


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
            "Explain first, in two to four sentences of plain English:\n"
            "- what the right answer is, and how you get to it\n"
            "- if the student is wrong, the step where their answer goes wrong\n"
            "Write for someone who is learning, not for a marker. A reply with no\n"
            "explanation is no use to the student.\n\n"
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

    [OPEN] also returns None. It says the question has no single right answer,
    which is a different thing from a missing marker but wants the same
    handling: show the prose, draw no verdict. Nothing downstream can tell the
    two apart, which is deliberate — a fourth state would have to travel through
    the front end, the log schema and _EMPTY_REPLY to buy wording nobody has
    asked for yet.
    """
    m = _SIGNAL_RE.search(text)
    if m:
        marker = m.group(1).upper()
        clean = text[:m.start()]
        correct = None if marker == "OPEN" else marker == "CORRECT"
    else:
        clean, correct = text, None
    clean = _STRAY_MARKER_RE.sub('', clean)
    clean = _LEAD_IN_MARKER_RE.sub(' ', clean)
    clean = _INLINE_MARKER_RE.sub(' ', clean)
    clean = _CHECK_LINE_RE.sub('', clean)

    return re.sub(r'\n{3,}', '\n\n', clean).strip(), correct
