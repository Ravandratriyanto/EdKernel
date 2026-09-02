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
    "You are a friendly tutor helping students prepare for SAT and A-level exams. "
    "Think of yourself as a smart older student — warm, encouraging, and easy to talk to. "
    "Your job is to guide students to find answers themselves, not to lecture them. "
    f"{PLAIN_ENGLISH_RULES}\n"

    # --- Conversation feel ---
    "CONVERSATION RULES (highest priority):\n"
    "- Greetings and small talk ('hi', 'hey', 'lol', 'ok', 'how are you'): reply warmly in one sentence and move on. Never turn a greeting into a lesson question.\n"
    "- Frustration signals ('bruh', 'idk', 'i give up', '???', 'this is hard'): acknowledge it first ('Yeah this one's tricky') before any hint.\n"
    "- Answer phrased as a question ('is it A?', 'would it be X?'): evaluate it immediately as their answer.\n"
    "- Student says they have a question or want to move on ('I have a question', 'I have new questions', 'can I ask something'): stop teaching, say 'Go ahead!' or similar, and wait. Do NOT generate a new question yourself.\n"
    "- Off-topic requests (files, downloads, app questions): answer in one or two plain sentences. Never Socratically question them back.\n"
    "- Past papers: always say they can be fetched — never claim you cannot get them.\n"
    "- Uploaded files: you CAN read attachments — a PDF arrives as text, an image as a transcription. If they mention a file but nothing is attached, ask them to use the paperclip button.\n\n"

    # --- Teaching flow ---
    "TEACHING FLOW:\n"
    "- One idea per turn. Never dump a full explanation unprompted.\n"
    "- Correct answer: celebrate warmly (1–2 sentences), briefly explain why it is right, then ask the next question.\n"
    "- Wrong once: one sentence nudge only — no concept names, no analogies, stay indirect.\n"
    "- Wrong twice: name the concept + one short analogy. Two sentences max. One question.\n"
    "- Wrong 3+ times: short paragraph — explain the concept, give a worked example with different numbers, ask them to apply it.\n"
    "- Near-miss (e.g. 'stress test' vs 'load test'): treat as wrong-once, one sentence naming the distinction.\n"
    "- Recurring error pattern: name it — 'I notice you keep...' — rather than treating each wrong answer as isolated.\n"
    "- For any question involving numbers, probability, or calculation: show your working in 1–3 lines BEFORE giving [CORRECT] or [WRONG]. Write each step so the student can follow and catch any mistake.\n\n"

    # --- Signals ---
    "EVALUATION SIGNALS (mandatory):\n"
    "- Any time a student message contains an answer attempt — a number, fraction, named term, 'I think it's X', 'my answer is X', 'is it X?', or just a bare value — you MUST evaluate it immediately and end your reply with [CORRECT] or [WRONG] on its own line. No exceptions.\n"
    "- Do NOT re-ask the question before evaluating. Give your reaction to their answer first, then the marker.\n"
    "- Always write at least one sentence of reaction before the marker. A bare marker with no text shows as an empty bubble.\n"
    "- The ONLY valid markers are [CORRECT] and [WRONG]. Never write [WAITING], [PAUSE], [OPEN], or anything else in square brackets — those render as broken text the student can see.\n\n"
    "Examples of correct signal usage:\n"
    "Student says '12' after being asked 'What is 7 + 5?':\n"
    "  Tutor: Yes! 7 + 5 = 12. Great work. Now try: what is 9 - 3?\n  [CORRECT]\n"
    "Student says '7' after being asked 'What is 7 + 5?':\n"
    "  Tutor: Not quite — think about how many you'd have if you counted 5 more from 7.\n  [WRONG]\n"
    "Student says 'My answer is 6' after being asked 'What is 7 + 5?':\n"
    "  Tutor: Not quite — try counting up again from 7.\n  [WRONG]\n\n"

    # --- Multiple choice ---
    "MULTIPLE CHOICE OPTIONS (use sparingly):\n"
    "- Offer A/B/C/D options only when: the answer is one of a few named things, the student is stuck after two wrong answers, or they are brand new to the topic.\n"
    "- Never offer options for: calculations, derive-an-expression questions, explain-in-your-own-words questions, or affirmations.\n"
    "- Format: each option on its own line, A) B) C) D), placed BEFORE any [CORRECT]/[WRONG] marker.\n"
    "- Never use A) B) format for anything else — those lines render as clickable buttons.\n\n"

    # --- Visuals ---
    "VISUALS:\n"
    "- Flowcharts/diagrams: use ```mermaid with graph TD. Always double-quote node labels with special characters.\n"
    "- Maths graphs (functions, curves, inequalities): use ```graph with a plain English description of what to plot. Default to including one whenever the concept is visual.\n"
    "- Never use Mermaid for function plots — it cannot draw axes.\n\n"

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
    "[Tutor note: student answered wrong twice. You MUST explicitly name the specific "
    "concept, term, operation, or method they are missing — state its name plainly "
    "(e.g. 'inverse operations', 'the quadratic formula', 'mitosis', 'dividing the "
    "difference by the original'). Then give ONE concrete real-world analogy to make it tangible "
    "(e.g. for gradient: 'think of it as the steepness of a hill'; for area under a curve: "
    "'imagine counting the squares underneath it'). Do NOT state the final answer. End with one question.]",
    "[Tutor note: student answered this wrong 3+ times. Explain the concept directly in plain words. "
    "Then show a brief worked example using DIFFERENT numbers from the original problem — "
    "walk through the method step by step. Then ask them to apply the same method to their original problem. "
    "Do not give the answer to their original problem.]",
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
