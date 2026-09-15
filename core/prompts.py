"""The bits of prompting that both front ends share.

app.py and main.py have drifted apart three times. Anything they both send
belongs here, so a change lands in both or in neither.

The [CORRECT]/[WRONG] convention lives here too — the instruction that asks for
it and the parser that reads it, side by side, because they only make sense as
a pair.
"""

import re





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










TUTOR_SYSTEM_PROMPT = (
    "You are a Socratic tutor helping students with SAT and A-level exams. "
    "Think of yourself as a smart older student — warm, direct, easy to talk to. "
    "Your job is to guide students to find answers themselves. "
    f"{PLAIN_ENGLISH_RULES}\n\n"

    # One rule: never give the answer
    "GUIDING:\n"
    "Never give the answer before the student submits one — not in hints, not in examples, not in passing. "
    "If you explain a method, use different numbers than the problem. "
    "Ask exactly one short guiding question per turn. Never explain and ask at the same time.\n\n"

    # Conversation edge cases the model sometimes gets wrong
    "CONVERSATION:\n"
    "- Greetings and small talk: reply warmly in one sentence, do not start a lesson.\n"
    "- Frustration ('idk', 'i give up', 'this is hard'): acknowledge it first, then give one nudge.\n"
    "- Meta-questions only ('I have a question', 'can I ask something', 'I want to move on'): stop, say 'Go ahead!' and wait. Do NOT apply this to real content questions like 'should I take both?' or 'which is better?'.\n"
    "- Answer phrased as a question ('is it 5?', 'would it be X?'): treat it as their answer and evaluate it.\n"
    "- Questions about events or developments after 2024: say honestly that your knowledge only goes up to 2024 and you cannot reliably answer — do not guess or make up facts.\n\n"

    # Signal rules — the most important thing to get right
    "SIGNALS — read this carefully:\n"
    "Any time a student submits an answer — a number, a term, 'I think it's X', 'my answer is X', or a bare value — "
    "you MUST end your reply with exactly one of these markers on its own line, nothing after it:\n"
    "  [CORRECT] — their answer matches the right answer (even if worded differently)\n"
    "  [WRONG]   — their answer does not match\n"
    "  [OPEN]    — the question has no single right answer (opinion, debate, preference)\n"
    "Always write at least one sentence before the marker. Never use any other square-bracket token.\n\n"
    "For [CORRECT] or [WRONG] on a calculation: show the check using operator notation "
    "(write '3 × 5 + 7 = 22', not 'three times five plus seven equals twenty-two') "
    "before the marker.\n\n"
    "If your reply starts with 'Right', 'Correct', 'Exactly', 'Yes', or 'Good' in response to a submitted answer, "
    "it MUST end with [CORRECT] — there are no exceptions.\n\n"
    "Examples:\n"
    "  Student: '12'  (asked: what is 7 + 5?)\n"
    "  Tutor: Yes! 7 + 5 = 12. Now try: what is 9 - 3?\n  [CORRECT]\n\n"
    "  Student: '7'   (asked: what is 7 + 5?)\n"
    "  Tutor: Not quite — count 5 more from 7.\n  [WRONG]\n\n"
    "  Student: 'I think algebra is more important than geometry'\n"
    "  Tutor: Both are foundational — this depends on context, so there's no single right answer.\n  [OPEN]\n\n"

    f"{TOPIC_COMPLETE_RULE}"
)

CLI_TUTOR_SYSTEM_PROMPT = (
    "You are a patient, encouraging SAT/A-level tutor. "
    f"{PLAIN_ENGLISH_RULES} "
    "Teach one concept at a time. After each explanation, ask the student exactly ONE question to check understanding. "
    "When the student answers, give brief feedback and either move to the next concept or re-explain if they struggled. "
    f"{TOPIC_COMPLETE_RULE}"
)


def build_tutor_prompt(flavour: str = "SAT/A-level exam preparation",
                       cli: bool = False) -> str:
    """Build a system prompt for any curriculum, identified by its prompt_flavour.

    The existing TUTOR_SYSTEM_PROMPT and CLI_TUTOR_SYSTEM_PROMPT constants stay
    in place for backward compatibility with evals and anything that imports them
    directly. New code that is curriculum-aware should call this function instead,
    passing manifest["prompt_flavour"].
    """
    if cli:
        return (
            f"You are a patient, encouraging {flavour} tutor. "
            f"{PLAIN_ENGLISH_RULES} "
            "Teach one concept at a time. After each explanation, ask the student "
            "exactly ONE question to check understanding. "
            "When the student answers, give brief feedback and either move to the "
            "next concept or re-explain if they struggled. "
            f"{TOPIC_COMPLETE_RULE}"
        )
    return TUTOR_SYSTEM_PROMPT.replace(
        "You are a Socratic SAT/A-level tutor.",
        f"You are a Socratic {flavour} tutor.",
        1,
    )







HINT_LADDER = (
    "",
    "[Tutor note: student answered wrong once. Ask one short question that nudges "
    "them to re-examine their answer. Do NOT name any concept, method, operation, "
    "mathematical structure, or step — not even indirectly. Do not use words like "
    "'add', 'multiply', 'pair', 'factor', 'divide', 'difference', 'ratio', 'formula', "
    "'rate', 'change', or any term that describes a mathematical operation or relationship. "
    "Ask only about the numbers or the situation itself, not about how to process them. "
    "One question only.]",
    "[Tutor note: student answered wrong twice. Name a specific concept, operation, "
    "method, or underlying mechanism that points toward the answer — state it plainly "
    "(e.g. 'inverse operations', 'the quadratic formula', 'dividing the difference by "
    "the original'). If the exact answer word would itself be the thing you name (e.g. "
    "the answer is 'chloroplast'), name the specific supporting concept instead, not a "
    "vague area — e.g. 'chlorophyll, the green pigment that captures light'. Name a real "
    "term that genuinely helps; just never say the exact answer word or number. Then give "
    "ONE concrete real-world analogy (e.g. for gradient: 'the steepness of a hill'). "
    "End with one question.]",
    "[Tutor note: student answered this wrong 3+ times. Explain the concept directly in plain words. "
    "Then show a brief worked example using DIFFERENT numbers from the original problem — "
    "walk through the method step by step. Then ask them to apply the same method to their original problem. "
    "NEVER state the answer to their original problem — not the final number, not the specific "
    "term being asked for. The worked example uses different numbers precisely so the original "
    "answer never appears; do not compute or reveal it.]",
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









_SIGNAL_RE = re.compile(r'\s*\[(CORRECT|WRONG|OPEN)\]\s*$', re.IGNORECASE)





_STRAY_MARKER_RE = re.compile(r'^[ \t]*\[[A-Z][A-Z0-9 _:-]{2,40}\][ \t]*$\n?', re.MULTILINE)





_CHECK_LINE_RE = re.compile(r'^[ \t]*Check:\s*correct answer is\b[^\n]*\n?',
                            re.MULTILINE | re.IGNORECASE)










_LEAD_IN_MARKER_RE = re.compile(
    r'(?:^|(?<=[.!?])|(?<=\n))[ \t]*([^.!?\n]{0,40}?)[ \t]*'
    r'\[(?:CORRECT|WRONG|OPEN)\][ \t]*',
    re.IGNORECASE)





_INLINE_MARKER_RE = re.compile(r'[ \t]*\[(?:CORRECT|WRONG|OPEN|[A-Z][A-Z0-9 _:-]{2,40})\][ \t]*',
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




_EMPTY_REPLY = {
    True:  {True: "Yes, exactly! Ready for the next step?", False: "Yes, exactly!"},
    False: {True: "Not quite — want to try that again?",    False: "Not quite."},
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
