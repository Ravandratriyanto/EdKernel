import io
import os
import re
import ast
import json
import time
import base64
import hashlib
from pathlib import Path
from urllib.parse import urlparse
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory, send_file, g
from werkzeug.utils import secure_filename
from pypdf import PdfReader
from llm.client import generate, chat
from rag.retrieve import retrieve
from vision.image_handler import transcribe
from diagram_shots import shot_messages
from sessionlog import log_turn, attachment_meta, list_sessions, session_turns
import pdftext
import users
from ratelimit import RateLimiter
# Shared with main.py so the two front ends cannot drift on the verdict signal.
from prompts import build_check_prompt, strip_signal as _strip_signal
load_dotenv()

app = Flask(__name__, static_folder="static")

# ── auth ─────────────────────────────────────────────────────────────────────

users.init()
# Timed-out rows serve no purpose and user_for_token already refuses them.
# Only runs at boot, which is enough for a server that is restarted often; a
# long-lived one is also swept on each successful login below.
users.purge_expired()

SESSION_COOKIE = "ollm_session"

# A secure cookie is only sent over https. Setting it on plain http does not
# warn — the browser silently drops the cookie and the app looks broken with no
# error anywhere. So it follows the deployment: export OLLM_HTTPS=1 when this
# sits behind TLS, and leave it unset on localhost.
COOKIE_SECURE = os.environ.get("OLLM_HTTPS", "").strip().lower() in {"1", "true", "yes"}

# 8 failures per 15 minutes, counted against the IP and the username separately.
# Aimed at online guessing, not at a determined attacker: see ratelimit.py for
# what this does not cover.
_login_limiter = RateLimiter(max_failures=8, window_seconds=15 * 60)


def _login_keys(username: str) -> tuple:
    """The two buckets a login attempt counts against.

    IP alone is not enough — an attacker with a pool of addresses would get 8
    tries each against one account. Username alone is not enough either, or one
    machine could work through a list of accounts unhindered.
    """
    return (f"ip:{request.remote_addr}",
            f"user:{(username or '').strip().lower()}")

# Endpoints reachable without logging in. Everything else is closed by
# default — a new route is protected the moment it exists, rather than the
# moment somebody remembers to decorate it.
_OPEN_ENDPOINTS = {"index", "static", "api_register", "api_login",
                   "api_logout", "api_me"}


@app.before_request
def _load_user():
    """Turn the session cookie into g.user, and refuse anonymous callers."""
    g.user = users.user_for_token(request.cookies.get(SESSION_COOKIE, ""))
    if request.endpoint in _OPEN_ENDPOINTS:
        return None
    if g.user is None:
        return jsonify({"error": "Not logged in"}), 401
    return None


def _auth_response(user: dict, token: str):
    """Reply to a successful login or registration, carrying the cookie."""
    resp = jsonify({"user": {"id": user["id"], "username": user["username"]}})
    resp.set_cookie(
        SESSION_COOKIE, token,
        max_age=users.SESSION_TTL_SECONDS,
        httponly=True,          # JavaScript can't read it, so an XSS bug can't steal it
        samesite="Lax",
        secure=COOKIE_SECURE,   # https only when OLLM_HTTPS is set
    )
    return resp


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.json or {}

    # Registration is an enumeration oracle: "That username is taken" confirms
    # an account exists, which is exactly what api_login refuses to reveal. The
    # message has to stay — someone picking a name deserves to know it is gone
    # — so the rate limit is what stops it being read in bulk. IP only: keying
    # on the username would let anyone lock a name out of being registered.
    ip_key = f"register-ip:{request.remote_addr}"
    wait = _login_limiter.retry_after(ip_key)
    if wait:
        resp = jsonify({"error": "Too many attempts. Try again later."})
        resp.headers["Retry-After"] = str(wait)
        return resp, 429

    try:
        uid = users.create_user(data.get("username", ""), data.get("password", ""))
    except users.UserError as e:
        _login_limiter.record_failure(ip_key)
        return jsonify({"error": str(e)}), 400

    _login_limiter.clear(ip_key)
    username = (data.get("username") or "").strip()
    return _auth_response({"id": uid, "username": username},
                          users.create_session(uid))


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    keys = _login_keys(username)

    wait = _login_limiter.retry_after(*keys)
    if wait:
        # Checked before the password is verified, so a blocked caller cannot
        # use this endpoint to test guesses at all.
        resp = jsonify({"error": "Too many failed logins. Try again later."})
        resp.headers["Retry-After"] = str(wait)
        return resp, 429

    uid = users.authenticate(data.get("username", ""), data.get("password", ""))
    if uid is None:
        _login_limiter.record_failure(*keys)
        # One message for both cases. "No such user" would confirm which
        # usernames exist.
        return jsonify({"error": "Wrong username or password."}), 401

    # A correct password clears the count, so a student who mistypes four times
    # and then gets it right is not left half-way to a lockout.
    _login_limiter.clear(*keys)
    users.purge_expired()
    return _auth_response({"id": uid, "username": username},
                          users.create_session(uid))


@app.route("/api/logout", methods=["POST"])
def api_logout():
    users.delete_session(request.cookies.get(SESSION_COOKIE, ""))
    resp = jsonify({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@app.route("/api/me")
def api_me():
    """Who am I? The page asks this on load to decide login screen or app."""
    return jsonify({"user": g.user})


def _key(data: dict, field: str, env_var: str) -> str:
    """A key typed into the UI wins; otherwise fall back to the one in .env."""
    return (data.get(field) or "").strip() or os.environ.get(env_var, "").strip()

TUTOR_SYSTEM_PROMPT = (
    "You are a Socratic SAT/A-level tutor. Your job is to guide the student to discover answers themselves — never lecture or dump information. "
    "Write in the simplest English you can. Short sentences. Everyday words a 12-year-old would understand. "
    "Never use a long or academic word where a short one works: say 'use' not 'utilise', 'so' not 'therefore', 'find' not 'determine'. "
    "One idea per sentence. No filler, no throat-clearing, no phrases like 'let us consider' or 'it is important to note'. "
    "You may use a subject term (like 'mitochondria' or 'derivative') when it is the thing being taught — but the first time it appears, "
    "immediately explain what it means in plain words. Assume English may be the student's second language. "
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
    "When a process diagram or flowchart would help (cycles, cause-effect, steps), include it as a ```mermaid code block using 'graph TD'. "
    "Mermaid syntax rule: always wrap node labels in double quotes when they contain special characters. Example: A[\"Step one\"] --> B[\"Step two\"]. "
    "NEVER use Mermaid for mathematical function plots — Mermaid cannot draw axes or curves. "
    "For mathematical graphs (plotting functions, comparing curves, showing derivatives), use a ```graph code block containing a plain English description of what to plot. "
    "Example: ```graph\nPlot f(x) = x^2 and f'(x) = 2x on the same axes from x = -3 to x = 3, with a legend\n``` "
    "When the entire topic has been fully explored through dialogue, end your response with the exact phrase 'Topic complete.'"
)

GRAPH_SYSTEM_PROMPT = (
    "You are a Python matplotlib code generator. Output ONLY valid Python code with no explanation and no markdown fences. "
    "The following are already in scope — do NOT import or redefine them: plt, np. "
    "Write only the plotting logic. Rules:\n"
    "- Use LaTeX notation in all labels, titles, and legends: wrap math in $...$. "
    "Example: label=r'$f(x) = x^{2}$'. Always use r-strings for LaTeX.\n"
    "- Do NOT call plt.savefig(), plt.show(), plt.close(), or import anything.\n"
    "- End with plt.tight_layout().\n"
    "- NEVER invent real-world data. If the graph needs figures you do not "
    "have — prices, populations, sales, historical values — do not guess them. "
    "Output exactly NEED_REAL_DATA and nothing else.\n"
    "- Every worked example uses ONE standard market: demand P = 10 - 0.8Q, "
    "supply P = 2 + 0.8Q. They cross at Q = 5, P = 6. Reuse those equations.\n"
    "- A ceiling or maximum must sit BELOW P = 6. A floor, minimum or union "
    "wage must sit ABOVE P = 6. A line level with 6 shows nothing.\n"
    "- A horizontal line at price p meets demand at Q = (10 - p) / 0.8 and "
    "supply at Q = (p - 2) / 0.8. Compute both before placing any marker.\n"
    "- Never put a marker at a point that is not on a curve you plotted."
)

# Generated plotting code is checked against an allowlist before it runs, so a
# construct nobody thought of is blocked by default rather than allowed by
# default. The abstract bases (ast.operator and friends) cover every arithmetic
# and comparison operator without listing them one by one.
_GRAPH_ALLOWED_NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.For, ast.If, ast.Pass,
    ast.Call, ast.keyword, ast.Name, ast.Attribute, ast.Subscript, ast.Slice, ast.Starred,
    ast.Constant, ast.Tuple, ast.List, ast.Dict, ast.Set,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)

# These write files or open windows — the route renders the figure itself.
_GRAPH_BANNED_ATTRS = {"savefig", "show", "close", "imsave"}

# None of these are in _GRAPH_BUILTINS, so they would already die with a
# NameError. Naming them here rejects the code before it runs and says why.
_GRAPH_BANNED_NAMES = {
    "exec", "eval", "compile", "open", "input", "breakpoint", "help",
    "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr",
}

# exec() with no "__builtins__" key gets the real builtins injected, which is
# what left __import__ reachable. An explicit minimal set closes that.
_GRAPH_BUILTINS = {
    "abs": abs, "min": min, "max": max, "sum": sum, "round": round, "pow": pow,
    "range": range, "len": len, "enumerate": enumerate, "zip": zip,
    "sorted": sorted, "reversed": reversed,
    "int": int, "float": float, "str": str, "bool": bool,
    "list": list, "tuple": tuple, "dict": dict, "set": set,
}


def _check_graph_code(code: str) -> str | None:
    """Return why generated plotting code is unsafe, or None if it's fine."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"it did not parse: {e.msg}"

    for node in ast.walk(tree):
        if not isinstance(node, _GRAPH_ALLOWED_NODES):
            return f"{type(node).__name__} is not allowed"
        # Leading underscores are how you climb out of a restricted namespace,
        # e.g. ().__class__.__base__.__subclasses__().
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                return f"attribute {node.attr!r} is not allowed"
            if node.attr in _GRAPH_BANNED_ATTRS:
                return f"{node.attr}() is not allowed — the server renders the figure"
        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                return f"name {node.id!r} is not allowed"
            if node.id in _GRAPH_BANNED_NAMES:
                return f"{node.id}() is not allowed"
    return None


def _render_png() -> str:
    """The current figure as base64 PNG. Closes the figure either way."""
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close("all")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


# A hardcoded run of numbers is data somebody typed, not data derived from a
# formula. When the model types it, the numbers are invented — asked for the
# price of gold it produced twelve monthly figures to two decimal places. The
# figure gets stamped so an invented series cannot look like a measured one.
_LITERAL_DATA_MIN = 4


def _has_literal_data(code: str) -> bool:
    """True if the code plots a hardcoded run of numbers rather than computing them."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            # bool subclasses int, so [True, False, True, False] would otherwise
            # count as four numbers.
            numbers = [e for e in node.elts
                       if isinstance(e, ast.Constant)
                       and isinstance(e.value, (int, float))
                       and not isinstance(e.value, bool)]
            if len(numbers) >= _LITERAL_DATA_MIN:
                return True
    return False


ALLOWED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PDF_TEXT_LIMIT  = 8000

# Downloaded past papers are cached here so the browser can ask for them by id
# instead of by URL — see _fetch_pdf for why that matters.
PAPER_CACHE_DIR = Path(__file__).parent / "data" / "papers"
PAPER_MAX_BYTES = 20 * 1024 * 1024   # a scanned A-level paper can be big; 20MB is plenty
PAPER_MAX_FETCH = 3                  # per search, to keep the request from crawling
VERIFY_OVERSHOOT = 3                 # spare questions, since the answer check drops some
_PAPER_ID_RE    = re.compile(r'^[0-9a-f]{16}$')
_GREETING_RE = re.compile(
    r"^\s*(?:h(?:i|ey|ello|igh)|yo|sup|good\s+(?:morning|afternoon|evening))"
    r"(?:\s+there)?\s*[!.?]*\s*$", re.IGNORECASE)

_FILLER_WORDS = {"test", "testing", "asdf", "abc", "stuff", "thing", "things",
                 "anything", "something", "idk", "none", "na"}

def _pdf_text(data: bytes) -> str:
    """Extract the text layer from PDF bytes. Empty string if it has none."""
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(pdftext.doc_pages(reader))


# A numbered question ("12." or "12)") at the start of a line, and the symbols
# that show up in maths but almost never in a copyright notice.
_QUESTION_NUM_RE = re.compile(r'^\s*\d{1,2}[\.\)]\s+\S', re.MULTILINE)
_MATH_CHARS      = set("=+×÷≤≥∫√^")


def _question_pages(data: bytes, budget: int = 7000) -> tuple[bool, str]:
    """Pull the pages that actually carry exam questions.

    Past-paper PDFs open with cover sheets, instructions and marketing, and a
    plain full-document extract is mostly that. Feeding it to the generator
    produces questions about the exam board rather than the maths, so pages are
    scored for question-likeness and the best ones are kept in reading order.

    Returns (has_text_layer, question_text). The two are different failures: a
    scan has no text at all, while a text PDF with nothing question-shaped is
    readable but not a paper. Only the first means "download it and use vision".
    """
    reader = PdfReader(io.BytesIO(data))

    has_text = False
    scored = []
    for i, text in enumerate(pdftext.doc_pages(reader)):
        if text.strip():
            has_text = True
        if len(text.strip()) < 80:
            continue
        score = (len(_QUESTION_NUM_RE.findall(text)) * 3
                 + text.count("?")
                 + sum(c in _MATH_CHARS for c in text) // 4)
        if score >= 3:
            scored.append((score, i, text))

    if not scored:
        return has_text, ""

    # Best pages first to fill the budget, then restore document order so a
    # multi-page question still reads correctly.
    scored.sort(key=lambda t: -t[0])
    kept, total = [], 0
    for score, i, text in scored:
        if total >= budget:
            break
        kept.append((i, text))
        total += len(text)

    kept.sort()
    return has_text, "\n\n".join(text for _, text in kept)[:budget]

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

# ── file upload ──────────────────────────────────────────────────────────────

@app.route("/api/upload", methods=["POST"])
def api_upload():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file provided"}), 400

    name = file.filename.lower()
    ext  = "." + name.rsplit(".", 1)[-1] if "." in name else ""

    if ext == ".pdf":
        text = _pdf_text(file.read())
        return jsonify({"type": "pdf", "text": text[:PDF_TEXT_LIMIT], "name": file.filename})

    if ext in ALLOWED_IMAGES:
        b64 = base64.b64encode(file.read()).decode("utf-8")
        return jsonify({"type": "image", "b64": b64, "name": file.filename})

    return jsonify({"error": f"Unsupported file type: {ext}"}), 400

# ── graph generation ─────────────────────────────────────────────────────────

@app.route("/api/graph", methods=["POST"])
def api_graph():
    data        = request.json
    description = data.get("description", "")
    provider    = data.get("provider", "ollama")
    model       = data.get("model", "gemma4")
    host        = data.get("host", "http://localhost:11434")
    api_key     = _key(data, "api_key", "API_KEY")

    if not description:
        return jsonify({"error": "No description provided"}), 400

    messages = [{"role": "system", "content": GRAPH_SYSTEM_PROMPT}]
    messages += shot_messages(description)     # [] when nothing is close enough
    messages.append({"role": "user",
                     "content": f"Generate a graph for: {description}"})
    raw_code = chat(messages, model=model, host=host, provider=provider, api_key=api_key)

    if "NEED_REAL_DATA" in raw_code:
        return jsonify({"error": "That graph needs real data I do not have. "
                                 "Give me the figures and I will plot them, or "
                                 "ask for a diagram that shows the shape of the "
                                 "relationship instead."}), 400

    # Strip accidental markdown fences and any savefig/show/close calls
    code = re.sub(r"^```(?:python)?\n?", "", raw_code.strip())
    code = re.sub(r"\n?```$", "", code)
    code = re.sub(r"plt\.(savefig|show|close)\(.*?\)\n?", "", code)
    code = re.sub(r"^\s*(?:import|from)\s+.*$", "", code, flags=re.MULTILINE)

    err = _check_graph_code(code)
    if err:
        return jsonify({"error": f"Refused to run the generated graph code — {err}"}), 400

    try:
        plt.close("all")
        exec(code, {"__builtins__": _GRAPH_BUILTINS, "plt": plt, "np": np})  # noqa: S102
        if _has_literal_data(code):
            plt.gcf().text(0.99, 0.01, "Illustrative — values are not real data",
                           ha="right", va="bottom", fontsize=7, color="#b45309")
        return jsonify({"image": _render_png()})
    except Exception as e:
        plt.close("all")
        return jsonify({"error": str(e)}), 500

# ── learn endpoints ──────────────────────────────────────────────────────────

@app.route("/api/start", methods=["POST"])
def api_start():
    data       = request.json
    topic      = data.get("topic", "")
    provider   = data.get("provider", "ollama")
    model      = data.get("model", "gemma4")
    host       = data.get("host", "http://localhost:11434")
    api_key      = _key(data, "api_key", "API_KEY")
    attachment   = data.get("attachment")
    vision_model = data.get("vision_model", "")

    context_chunks = retrieve(topic)
    context        = "\n\n".join(context_chunks) if context_chunks else ""
    context_prefix = f"Reference material:\n{context}\n\n" if context else ""

    user_msg = {"role": "user", "content": f"{context_prefix}Teach me about: {topic}"}
    if attachment:
        _apply_attachment(user_msg, attachment, provider, model, host, api_key, vision_model)

    messages = [{"role": "system", "content": TUTOR_SYSTEM_PROMPT}, user_msg]
    started  = time.monotonic()
    # Keep the raw reply: _strip_signal returns a plain str, which drops .usage.
    raw = chat(messages, model=model, host=host, provider=provider, api_key=api_key)
    response, _ = _strip_signal(raw)
    messages.append({"role": "assistant", "content": response})

    log_turn("start",
             session_id=data.get("session_id", ""),
             user_id=g.user["id"],
             mode="learn", topic=topic,
             provider=provider, model=model,
             input=topic, output=response,
             attachment=attachment_meta(attachment),
             tokens=getattr(raw, "usage", {}),
             latency_ms=round((time.monotonic() - started) * 1000))

    return jsonify({"response": response, "messages": _strip_images(messages), "done": "Topic complete." in response})

@app.route("/api/reply", methods=["POST"])
def api_reply():
    data         = request.json
    messages     = data.get("messages", [])
    user_input   = data.get("input", "")
    provider     = data.get("provider", "ollama")
    model        = data.get("model", "gemma4")
    host         = data.get("host", "http://localhost:11434")
    api_key      = _key(data, "api_key", "API_KEY")
    attachment   = data.get("attachment")
    vision_model = data.get("vision_model", "")
    wrong_streak = int(data.get("wrong_streak", 0))
    tavily_key   = _key(data, "tavily_key", "TAVILY_KEY")
    topic        = data.get("topic", "")

    # "just give me the papers" — fetch them instead of tutoring at the student.
    # The reply is written here rather than by the model: the model has no way to
    # know whether the download actually succeeded, and this turn must not be
    # answered with another Socratic question.
    if _mentions_papers(user_input):
        started = time.monotonic()
        intent = _paper_intent(user_input, topic, model=model, host=host,
                               provider=provider, api_key=api_key)
        if intent["wants_papers"]:
            reply, papers = _papers_for_chat(intent["topic"], tavily_key)
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": reply})
            # This branch used to return without logging, which left a hole in
            # the middle of any session that fetched papers.
            log_turn("papers",
                     session_id=data.get("session_id", ""),
                     user_id=g.user["id"],
                     mode="learn", topic=intent["topic"] or topic,
                     provider=provider, model=model,
                     input=user_input, output=reply,
                     correct=None, wrong_streak=wrong_streak,
                     attachment=attachment_meta(attachment),
                     tokens={},          # _paper_intent's usage is not metered yet
                     latency_ms=round((time.monotonic() - started) * 1000))
            return jsonify({
                "response": reply,
                "messages": _strip_images(messages),
                "done": False,
                "correct": None,
                "papers": papers,
            })
        # Not a papers request after all — fall through to the tutor as normal.

    hint_note = ""
    if wrong_streak == 1:
        hint_note = "\n\n[Tutor note: student answered this wrong once — give a slightly more specific clue than your first hint.]"
    elif wrong_streak == 2:
        hint_note = "\n\n[Tutor note: student answered this wrong twice — give a direct clue that names the key concept.]"
    elif wrong_streak >= 3:
        hint_note = "\n\n[Tutor note: student answered this wrong 3+ times — directly explain the concept they are missing, then ask them to apply it.]"

    user_msg = {"role": "user", "content": user_input + hint_note}
    if attachment:
        _apply_attachment(user_msg, attachment, provider, model, host, api_key, vision_model)

    messages.append(user_msg)
    started = time.monotonic()
    raw = chat(messages, model=model, host=host, provider=provider, api_key=api_key)
    response, correct = _strip_signal(raw)
    messages.append({"role": "assistant", "content": response})

    log_turn("reply",
             session_id=data.get("session_id", ""),
             user_id=g.user["id"],
             mode="learn", topic=topic,
             provider=provider, model=model,
             input=user_input, output=response,
             correct=correct, wrong_streak=wrong_streak,
             attachment=attachment_meta(attachment),
             tokens=getattr(raw, "usage", {}),
             latency_ms=round((time.monotonic() - started) * 1000))

    return jsonify({
        "response": response,
        "messages": _strip_images(messages),
        "done": "Topic complete." in response,
        "correct": correct,
    })

# ── session history ──────────────────────────────────────────────────────────

_SESSION_ID_MAX = 64
# The events that make up a lesson. A "check" is a one-shot, not a conversation.
_REPLAYABLE = ("start", "reply", "papers")


def _rebuild_messages(turns: list[dict]) -> list[dict]:
    """Turn logged rows back into a messages array the tutor can continue from.

    The log stores the student's raw input, not the message actually sent, so
    the RAG context and the [Tutor note: ...] nudge are both dropped. Losing the
    note is right — it applied to one turn. Losing the context is a real gap:
    a resumed lesson has no reference material behind its opening question.
    """
    messages = [{"role": "system", "content": TUTOR_SYSTEM_PROMPT}]
    for turn in turns:
        if turn.get("event") not in _REPLAYABLE:
            continue
        text = (turn.get("input") or "").strip()
        if turn.get("event") == "start":
            text = f"Teach me about: {text}"
        meta = turn.get("attachment")
        if meta:
            # The bytes were never logged, by design. Name the file so the tutor
            # does not answer as if the student had sent nothing at all.
            text += (f"\n\n[The student attached a {meta.get('type', 'file')}: "
                     f"{meta.get('name', '')}. It is not available in this "
                     f"resumed session.]")
        messages.append({"role": "user", "content": text})
        messages.append({"role": "assistant", "content": turn.get("output") or ""})
    return messages


@app.route("/api/sessions")
def api_sessions():
    return jsonify({"sessions": list_sessions(g.user["id"])})


@app.route("/api/sessions/<session_id>")
def api_session(session_id: str):
    if len(session_id) > _SESSION_ID_MAX:
        return jsonify({"error": "bad session id"}), 400
    turns = session_turns(session_id, g.user["id"])
    if not turns:
        # Same 404 whether the session is missing or belongs to someone else,
        # so the reply never confirms that another student's lesson exists.
        return jsonify({"error": "no such session"}), 404

    # Show exactly the turns the rebuild used, so the transcript on screen can
    # never disagree with the history the model is given.
    lesson = [t for t in turns if t.get("event") in _REPLAYABLE]
    shown  = lesson or turns            # a check-only session still shows its turns

    return jsonify({
        "session_id": session_id,
        "mode":  turns[0].get("mode", "learn"),
        "topic": turns[0].get("topic", ""),
        "turns": [{"event":   t.get("event", ""),
                   "input":   t.get("input", ""),
                   "output":  t.get("output", ""),
                   "correct": t.get("correct")} for t in shown],
        "messages":  _rebuild_messages(lesson),
        "resumable": bool(lesson),
    })

# ── check endpoint ───────────────────────────────────────────────────────────

@app.route("/api/check", methods=["POST"])
def api_check():
    data       = request.json
    question   = data.get("question", "")
    answer     = data.get("answer", "")
    provider   = data.get("provider", "ollama")
    model      = data.get("model", "gemma4")
    host       = data.get("host", "http://localhost:11434")
    api_key      = _key(data, "api_key", "API_KEY")
    attachment   = data.get("attachment")
    vision_model = data.get("vision_model", "")

    context_chunks = retrieve(question)
    context        = "\n\n".join(context_chunks) if context_chunks else ""
    context_prefix = f"Reference material:\n{context}\n\n" if context else ""

    if attachment and attachment.get("type") == "image" and provider == "ollama":
        messages = [
            {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_check_prompt(
                    question, answer, context_prefix=context_prefix,
                    note="The student also attached an image for context. "),
                "images": [attachment["b64"]],
            },
        ]
        started  = time.monotonic()
        raw      = chat(messages, model=model, host=host, provider=provider, api_key=api_key)
        response, correct = _strip_signal(raw)
        log_turn("check",
                 session_id=data.get("session_id", ""),
                 user_id=g.user["id"],
                 mode="check", topic=question,
                 provider=provider, model=model,
                 input=answer, output=response,
                 correct=correct,
                 attachment=attachment_meta(attachment),
                 tokens=getattr(raw, "usage", {}),
                 latency_ms=round((time.monotonic() - started) * 1000))
        return jsonify({"response": response, "correct": correct})

    pdf_context = f"Attached document:\n{attachment['text']}\n\n" if attachment and attachment.get("type") == "pdf" else ""

    # Providers without image input get the question transcribed to text instead.
    image_context = ""
    if attachment and attachment.get("type") == "image":
        image_context = _transcription_note(attachment, provider, model, host, api_key, vision_model).strip() + "\n\n"

    prompt   = build_check_prompt(
        question, answer, context_prefix=f"{context_prefix}{pdf_context}{image_context}")
    started  = time.monotonic()
    raw      = generate(prompt, model=model, host=host, provider=provider, api_key=api_key)
    response, correct = _strip_signal(raw)
    log_turn("check",
             session_id=data.get("session_id", ""),
             user_id=g.user["id"],
             mode="check", topic=question,
             provider=provider, model=model,
             input=answer, output=response,
             correct=correct,
             attachment=attachment_meta(attachment),
             tokens=getattr(raw, "usage", {}),
             latency_ms=round((time.monotonic() - started) * 1000))
    return jsonify({"response": response, "correct": correct})

# ── helpers ──────────────────────────────────────────────────────────────────

def _apply_attachment(msg: dict, attachment: dict, provider: str, model: str = "",
                      host: str = "", api_key: str = "", vision_model: str = ""):
    if attachment.get("type") == "image":
        name = attachment.get("name", "image")
        if provider == "ollama":
            msg["images"] = [attachment["b64"]]
            msg["content"] += f"\n\n(Student attached image: {name})"
        else:
            msg["content"] += _transcription_note(attachment, provider, model, host, api_key, vision_model)
    elif attachment.get("type") == "pdf":
        msg["content"] += f"\n\nAttached document ({attachment.get('name', 'file')}):\n{attachment['text']}"

def _transcription_note(attachment: dict, provider: str, model: str, host: str,
                        api_key: str, vision_model: str) -> str:
    """Transcribe an image to text for providers that can't take image input."""
    name = attachment.get("name", "image")
    try:
        text = transcribe(attachment["b64"], name=name, provider=provider,
                          model=model, host=host, api_key=api_key, vision_model=vision_model)
    except Exception as e:
        app.logger.warning("Image transcription failed for %s: %s", name, e)
        return f"\n\n(Student attached image: {name} — could not be read: {e})"
    return f"\n\nThe student attached an image ({name}). Transcription:\n{text}"

def _strip_images(messages: list) -> list:
    return [{"role": m["role"], "content": m["content"]} for m in messages]

# ── past papers ─────────────────────────────────────────────────────────────

PAPER_DOMAINS = [
    "physicsandmathstutor.com",
    "savemyexams.co.uk",
    "aqa.org.uk",
    "cambridgeinternational.org",
    "ocr.org.uk",
    "qualifications.pearson.com",
    "collegeboard.org",
    "pastpapers.co",
    "revisely.co.uk",
    "znotes.org",
]

PAPER_GEN_PROMPT = (
    "You are an SAT/A-level exam question writer.\n"
    "Read the content below from past papers and generate {n} multiple-choice questions "
    "that test understanding of key concepts.\n\n"
    "Use this EXACT format — no deviations:\n\n"
    "Q1. Question text here\n"
    "A) First option\n"
    "B) Second option\n"
    "C) Third option\n"
    "D) Fourth option\n"
    "[ANSWER: B]\n\n"
    "Rules:\n"
    "- Number questions Q1, Q2, Q3 etc.\n"
    "- Always exactly 4 options: A B C D\n"
    "- Always end each question with [ANSWER: X] on its own line\n"
    "- One correct answer, three plausible distractors\n"
    "- Match SAT/A-level difficulty\n"
    "- Blank line between questions\n"
    "- Base every question on the subject matter being examined. Ignore cover pages, instructions, "
    "copyright notices, exam board names and any marketing text — never write a question about the "
    "exam board, the test itself, or the organisation that published the paper\n\n"
    "Past paper content:\n{content}"
)

def _allowed_paper_host(url: str) -> bool:
    """True only for the revision sites in PAPER_DOMAINS.

    Checked on the parsed hostname, never with a substring test — otherwise
    `evil.com/?x=aqa.org.uk` would pass.
    """
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in PAPER_DOMAINS)


def _fetch_pdf(url: str) -> bytes | None:
    """Download a past paper. Returns None on any failure — one bad paper
    should never take down the whole search."""
    if not _allowed_paper_host(url):
        return None
    try:
        with requests.get(url, timeout=20, stream=True) as resp:
            resp.raise_for_status()
            # Servers hand back HTML error pages with a 200 all the time, so
            # trust the bytes over the headers.
            ctype = resp.headers.get("Content-Type", "").lower()
            if "pdf" not in ctype and not url.lower().endswith(".pdf"):
                return None

            chunks, total = [], 0
            for chunk in resp.iter_content(64 * 1024):
                total += len(chunk)
                if total > PAPER_MAX_BYTES:
                    return None
                chunks.append(chunk)
    except Exception:
        return None

    data = b"".join(chunks)
    return data if data.startswith(b"%PDF") else None


def _cache_paper(url: str, title: str, data: bytes) -> str:
    """Store a fetched paper and return the id the browser uses to ask for it."""
    paper_id = hashlib.sha256(url.encode()).hexdigest()[:16]
    PAPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (PAPER_CACHE_DIR / f"{paper_id}.pdf").write_bytes(data)
    # Sidecar so the download name and source survive a restart.
    (PAPER_CACHE_DIR / f"{paper_id}.json").write_text(
        json.dumps({"url": url, "title": title}))
    return paper_id


@app.route("/api/papers/download/<paper_id>")
def api_paper_download(paper_id: str):
    # The id is used to build a path, so it must be exactly what we generated.
    if not _PAPER_ID_RE.match(paper_id):
        return jsonify({"error": "Bad paper id"}), 400

    pdf_path = PAPER_CACHE_DIR / f"{paper_id}.pdf"
    if not pdf_path.is_file():
        return jsonify({"error": "Paper not in cache — run the search again"}), 404

    meta_path = PAPER_CACHE_DIR / f"{paper_id}.json"
    title = json.loads(meta_path.read_text()).get("title", "") if meta_path.is_file() else ""
    # The title comes from a page we don't control, so never trust it as a filename.
    name = secure_filename(title) or paper_id
    if not name.lower().endswith(".pdf"):
        name += ".pdf"

    return send_file(pdf_path, as_attachment=True, download_name=name,
                     mimetype="application/pdf")


VERIFY_PROMPT = (
    "You are checking the answer key of a multiple-choice exam paper.\n"
    "Solve every question below from scratch and decide the correct option yourself. "
    "Work through the reasoning briefly for each one — do not guess from how the options look.\n"
    "If a question is unanswerable, contradictory, or no option is correct, answer X for it.\n\n"
    "After your working, end your reply with a final block in exactly this format and nothing after it:\n"
    "FINAL\n"
    "Q1: B\n"
    "Q2: D\n\n"
    "Questions:\n{questions}"
)

_Q_BLOCK_RE  = re.compile(r'\n(?=Q\d+\.)')
_Q_OPTION_RE = re.compile(r'^([A-D])\)\s*(.+)$', re.MULTILINE)
_Q_ANSWER_RE = re.compile(r'\[ANSWER:\s*([A-D])\]', re.IGNORECASE)
_VERDICT_RE  = re.compile(r'^Q(\d+)\s*:\s*([A-DX])\s*$', re.MULTILINE | re.IGNORECASE)


def _parse_questions(raw: str) -> list[dict]:
    """Pull Q/options/key out of the generator's output.

    Mirrors parsePaperQuestions() in the frontend — the same shape has to be
    understood here so the key can be checked before the browser ever sees it.
    """
    questions = []
    for block in _Q_BLOCK_RE.split(raw or ""):
        if not block.strip():
            continue
        options = _Q_OPTION_RE.findall(block)
        answer  = _Q_ANSWER_RE.search(block)
        if len(options) < 2 or not answer:
            continue
        text = _Q_OPTION_RE.split(block)[0]
        text = re.sub(r'^Q\d+\.\s*', '', text).strip()
        if text:
            questions.append({"text": text, "options": options,
                              "answer": answer.group(1).upper()})
    return questions


def _format_questions(questions: list[dict]) -> str:
    """Rebuild the generator's wire format so the frontend parser is unchanged."""
    out = []
    for i, q in enumerate(questions, 1):
        lines = [f"Q{i}. {q['text']}"]
        lines += [f"{letter}) {body}" for letter, body in q["options"]]
        lines.append(f"[ANSWER: {q['answer']}]")
        out.append("\n".join(lines))
    return "\n\n".join(out)


def _verify_questions(questions: list[dict], **llm) -> tuple[list[dict], int]:
    """Re-solve each question and drop any whose key the solve disagrees with.

    One batched call rather than one per question — same signal, a fraction of
    the cost. The questions are sent WITHOUT their [ANSWER: X] lines so the
    checker cannot simply agree with the key it was meant to test.
    """
    if not questions:
        return questions, 0

    asked = "\n\n".join(
        "\n".join([f"Q{i}. {q['text']}"]
                  + [f"{letter}) {body}" for letter, body in q["options"]])
        for i, q in enumerate(questions, 1)
    )

    try:
        reply = chat([{"role": "user", "content": VERIFY_PROMPT.format(questions=asked)}], **llm)
    except Exception:
        # A failed check must not cost the student their questions; fall back to
        # the unverified set rather than returning nothing.
        return questions, 0

    tail = reply.rsplit("FINAL", 1)[-1]
    verdicts = {int(n): letter.upper() for n, letter in _VERDICT_RE.findall(tail)}

    kept = []
    for i, q in enumerate(questions, 1):
        verdict = verdicts.get(i)
        # No verdict parsed → keep it. Absence of evidence isn't a wrong answer,
        # and silently dropping questions on a formatting wobble is worse.
        if verdict is None or verdict == q["answer"]:
            kept.append(q)
    return kept, len(questions) - len(kept)


@app.route("/api/papers", methods=["POST"])
def api_papers():
    data        = request.json
    topic       = data.get("topic", "")
    tavily_key  = _key(data, "tavily_key", "TAVILY_KEY")
    n_questions = int(data.get("n_questions", 5))
    provider    = data.get("provider", "ollama")
    model_name  = data.get("model", "gemma4")
    host        = data.get("host", "http://localhost:11434")
    api_key     = _key(data, "api_key", "API_KEY")

    if not topic:
        return jsonify({"error": "No topic provided"}), 400
    if not tavily_key:
        return jsonify({"error": "Tavily API key required"}), 400

    try:
        results = _search_papers(topic, tavily_key)
    except Exception as e:
        return jsonify({"error": f"Search failed: {e}"}), 500

    if not results:
        return jsonify({"error": "No past paper content found for that topic. Try a more specific query."}), 404

    # Real papers first: download what we can and use its actual text, which is
    # far better grounding than a search snippet. Falls back to snippets when a
    # topic turns up no usable PDFs.
    papers, paper_texts = _collect_papers(results)

    if paper_texts:
        combined = "\n\n---\n\n".join(paper_texts)[:7000]
    else:
        content_parts = [r["content"] for r in results[:5] if r.get("content")]
        combined = "\n\n---\n\n".join(content_parts)[:7000]

    sources = [{"title": r.get("title", ""), "url": r.get("url", "")} for r in results[:5]]

    # Over-generate, because verification drops whatever it cannot confirm and
    # the student should still end up with the number they asked for.
    prompt = PAPER_GEN_PROMPT.format(n=n_questions + VERIFY_OVERSHOOT, content=combined)
    try:
        raw = chat(
            [{"role": "user", "content": prompt}],
            model=model_name, host=host, provider=provider, api_key=api_key,
        )
    except Exception as e:
        return jsonify({"error": f"Question generation failed: {e}"}), 500

    llm_kwargs = {"model": model_name, "host": host,
                  "provider": provider, "api_key": api_key}
    questions = _parse_questions(raw)
    verified, dropped = _verify_questions(questions, **llm_kwargs)
    verified = verified[:n_questions]

    if not verified:
        return jsonify({"error": "Generated questions all failed the answer check. "
                                 "Try a more specific topic."}), 502

    return jsonify({
        "questions": _format_questions(verified),
        "sources": sources,
        "papers": papers,
        # Lets the UI say where the questions came from, instead of implying
        # they are straight off a real paper when they came from snippets.
        "grounded": bool(paper_texts),
        "dropped": dropped,
    })


@app.route("/api/papers/hint", methods=["POST"])
def api_papers_hint():
    data         = request.json
    question     = data.get("question", "")
    options      = data.get("options", [])
    chosen       = data.get("chosen", "")
    correct      = data.get("correct", "")
    wrong_streak = int(data.get("wrong_streak", 1))
    provider     = data.get("provider", "ollama")
    model_name   = data.get("model", "gemma4")
    host         = data.get("host", "http://localhost:11434")
    api_key      = _key(data, "api_key", "API_KEY")

    opts_text = "\n".join(f"{o['letter']}) {o['text']}" for o in options)
    if wrong_streak == 1:
        instruction = "Give a subtle hint that nudges the student toward the right thinking. Stay indirect — do not name the concept yet."
    elif wrong_streak == 2:
        instruction = "Name the key concept the student needs but do not give away the answer."
    else:
        instruction = "Directly explain why the chosen option is wrong and explain the correct concept clearly. Then ask the student to confirm they understand."

    messages = [
        {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Past paper question:\n{question}\n\n{opts_text}\n\n"
            f"The student chose: {chosen}\n"
            f"The correct answer is: {correct}\n\n"
            f"{instruction} Write in plain, simple English. Do not end with [CORRECT] or [WRONG]."
        )},
    ]
    response = chat(messages, model=model_name, host=host, provider=provider, api_key=api_key)
    response, _ = _strip_signal(response)
    return jsonify({"response": response})

def _search_papers(topic: str, tavily_key: str) -> list[dict]:
    """Ask Tavily for past papers on a topic. Raises on failure."""
    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": tavily_key,
            "query": f"{topic} past paper exam questions SAT A-level filetype:pdf",
            "search_depth": "advanced",
            "include_domains": PAPER_DOMAINS,
            "include_raw_content": True,
            "max_results": 10,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def _collect_papers(results: list[dict]) -> tuple[list[dict], list[str]]:
    papers, paper_texts = [], []
    for r in results:
        if len(papers) >= PAPER_MAX_FETCH:
            break
        url = r.get("url", "")
        if not url.lower().endswith(".pdf"):
            continue
        data_bytes = _fetch_pdf(url)
        if not data_bytes:
            continue
        title = r.get("title", "") or url.rsplit("/", 1)[-1]
        try:
            has_text, text = _question_pages(data_bytes)
            text = text.strip()
        except Exception:
            has_text, text = False, ""
        paper_id = _cache_paper(url, title, data_bytes)
        papers.append({
            "id": paper_id,
            "title": title,
            "url": url,
            "download": f"/api/papers/download/{paper_id}",
            "scanned": not has_text,
            "no_questions": has_text and not text,
        })
        if text:
            paper_texts.append(text)
    return papers, paper_texts


# ── "just give me the papers" detection ─────────────────────────────────────
# Two stages. The keyword rules below are a cheap prefilter that decides whether
# a turn is worth asking about; _paper_intent() then makes one structured call to
# decide intent and topic together. The original objection to a classifier was
# that it would cost a call on every tutor turn — it does not, because a message
# that never mentions papers never gets that far.
#
# The regexes stay as the fallback for when that call fails, so a flaky model
# cannot cost the student the feature.

# Bare "papers" is included but only in the plural: "take some papers" is a
# request, while "explain this paper I uploaded" is not — and the fetch-verb
# requirement rules out "explain these papers" anyway.
_PAPER_NOUN = r"(?:past[\s-]?papers?|exam papers?|pdfs?|mark schemes?|real (?:exam )?questions?|papers)"
_FETCH_VERB = r"(?:get|give|fetch|find|download|send|show|grab|take|provide|need|want|have)"
_NEGATION   = r"(?:don'?t|do not|not|no need|nope|never|rather not|without)"
_ABOUT_RE = re.compile(r"^\s*(?:what|why|how|explain|describe|tell me about)\b", re.IGNORECASE)
# A verb, then the noun within a short window — "give me some past papers" hits,
# "what is a past paper?" does not.
_WANTS_PAPERS_RE = re.compile(
    rf"\b{_FETCH_VERB}\b[^.?!]{{0,40}}?\b{_PAPER_NOUN}\b", re.IGNORECASE)
# Negation anywhere before the noun in the same breath cancels it.
_NOT_PAPERS_RE = re.compile(
    rf"\b{_NEGATION}\b[^.?!]{{0,40}}?\b{_PAPER_NOUN}\b", re.IGNORECASE)


def _wants_papers(text: str) -> bool:
    """True when the student is asking for actual paper files."""
    if not text or _NOT_PAPERS_RE.search(text):
        return False
    if _WANTS_PAPERS_RE.search(text):
        return True
    # No fetch verb. On a short message the noun is the whole request, but a
    # question *about* papers is not a request for one.
    if _ABOUT_RE.search(text):
        return False
    return len(text.split()) <= 8 and bool(re.search(_PAPER_NOUN, text, re.I))

# "past papers on trigonometry" / "a paper for calculus" — an explicit subject in
# the request beats the lesson topic.
_TOPIC_IN_REQUEST_RE = re.compile(
    rf"{_PAPER_NOUN}\s+(?:on|for|about|in)\s+([a-z0-9][a-z0-9 '\-]{{2,50}})", re.IGNORECASE)


# "past papers for trigonometry please" — the politeness is not part of the topic.
_TOPIC_TRAIL_RE = re.compile(r"\b(?:please|pls|thanks|thank you|now|asap|ok)\b\s*$", re.IGNORECASE)


def _stated_topic(user_input: str) -> str:
    """The subject named in the request itself, or empty."""
    m = _TOPIC_IN_REQUEST_RE.search(user_input)
    return _TOPIC_TRAIL_RE.sub("", m.group(1)).strip() if m else ""


# The prefilter. Deliberately far wider than _wants_papers: no verb requirement
# and no negation cancel, because "can you not just fetch the whole pdf" is a
# request and the negation rule got that exactly backwards. The regex stops
# adjudicating and only decides whether a question is worth asking.
#
# Bare "paper" is singular here, unlike _PAPER_NOUN, which keeps it plural-only
# so the fallback behaves as it always has. "why won't you give me the paper" is
# a real request and has to reach the classifier; "explain this paper I uploaded"
# reaches it too and comes back false, which costs one call and gets the right
# answer instead of a lucky one.
_MENTIONS_PAPERS_RE = re.compile(rf"\b(?:{_PAPER_NOUN}|paper)\b", re.IGNORECASE)


def _mentions_papers(text: str) -> bool:
    """Cheap gate — only messages that mention papers cost an intent call."""
    return bool(text) and bool(_MENTIONS_PAPERS_RE.search(text))


PAPER_INTENT_PROMPT = (
    "You decide whether a student is asking to be given past exam paper files, "
    "and what subject those papers should be about.\n\n"
    "Return ONLY a JSON object. No prose, no code fences:\n"
    '{{"wants_papers": true or false, "topic": "subject" or null}}\n\n'
    "wants_papers is true when the student wants actual paper files handed to them, "
    "including when it is phrased as a complaint or a rhetorical question "
    '("can you not just fetch the whole pdf", "why won\'t you give me the paper").\n'
    "wants_papers is false when they ask what a past paper is, discuss a paper they "
    "already uploaded, or are simply answering a lesson question.\n\n"
    "topic is the exam subject to search for, as a short phrase a search engine would "
    'accept: "SAT", "trigonometry", "AS level Computer Science". '
    "Take it from the student's message when they name one. Otherwise fall back to the "
    "lesson topic below, shortened to just the subject — the lesson topic may be a full "
    "sentence, so strip it down to the subject. Use null only if neither gives a subject.\n\n"
    "Lesson topic: {lesson_topic}\n"
    "Student message: {message}"
)

# Greedy on purpose: models wrap JSON in fences and prose, and the outermost
# {...} is the object we want.
_JSON_OBJ_RE = re.compile(r'\{.*\}', re.DOTALL)


def _paper_intent(user_input: str, lesson_topic: str, **llm) -> dict:
    """Decide whether this turn is a papers request, and for what subject.

    Falls back to the keyword rules on any failure. A flaky model must not cost
    the student the feature — the same policy as _verify_questions.
    """
    fallback = {
        "wants_papers": _wants_papers(user_input),
        "topic": _stated_topic(user_input) or lesson_topic.strip(),
    }

    try:
        raw = chat([{"role": "user", "content": PAPER_INTENT_PROMPT.format(
            lesson_topic=lesson_topic.strip() or "(none)", message=user_input)}], **llm)
    except Exception:
        return fallback

    m = _JSON_OBJ_RE.search(raw or "")
    if not m:
        return fallback
    try:
        data = json.loads(m.group(0))
    except (ValueError, TypeError):
        return fallback

    # A model that returns the wrong shape is a failed call, not a "no".
    if not isinstance(data.get("wants_papers"), bool):
        return fallback

    topic = data.get("topic")
    topic = topic.strip() if isinstance(topic, str) else ""
    return {"wants_papers": data["wants_papers"], "topic": topic}


# A topic can still arrive as a whole sentence through the fallback path, and
# "3 papers on Can you please help me fetch AS level papers of Computer Science"
# reads like a bug. Past a certain length it has stopped being a subject, so the
# sentence drops the clause rather than swallowing it whole.
_TOPIC_PHRASE_MAX_WORDS = 6
_TOPIC_PHRASE_MAX_CHARS = 40


def _topic_phrase(topic: str) -> str:
    """' on <subject>' when the topic reads like one, otherwise empty."""
    t = " ".join((topic or "").split())
    if not t or len(t) > _TOPIC_PHRASE_MAX_CHARS or len(t.split()) > _TOPIC_PHRASE_MAX_WORDS:
        return ""
    return f" on {t}"


def _papers_for_chat(topic: str, tavily_key: str) -> tuple[str, list]:
    """Fetch papers for an already-resolved topic. Returns (reply text, papers).

    The topic is decided by _paper_intent() before this is called. _looks_like_topic
    stays as a backstop, because the fallback path can still hand over a raw
    lesson topic that was never a subject.
    """
    topic = (topic or "").strip()
    if topic and not _looks_like_topic(topic):
        return (f'I\'d be searching for "{topic}", which doesn\'t look like a '
                "subject. Which topic should I find papers on?", [])

    if not topic:
        return ("Which topic should I look for? Tell me the subject and I'll find papers on it.", [])
    if not tavily_key:
        return ("I can't search for papers — no Tavily API key is set. "
                "Add one in the settings bar or in the .env file.", [])

    try:
        results = _search_papers(topic, tavily_key)
    except Exception as e:
        return (f"The search for papers failed: {e}", [])

    papers, _ = _collect_papers(results)
    if not papers:
        return (f"I couldn't find a downloadable paper{_topic_phrase(topic)}. "
                "Try naming the exam board or a narrower subject.", [])

    # Say plainly what they got, including what is not usable and why.
    plural = "paper" if len(papers) == 1 else "papers"
    reply = (f"Here {'is' if len(papers) == 1 else 'are'} {len(papers)} {plural}"
             f"{_topic_phrase(topic)} — click to download.")
    scans = sum(1 for p in papers if p["scanned"])
    if scans:
        reply += (f" {scans} of them {'is a scan' if scans == 1 else 'are scans'}, "
                  "so the text can't be read out of it — but it still downloads.")
    reply += " Your lesson is still here whenever you want to carry on."
    return reply, papers


def _looks_like_topic(text: str) -> bool:
    """Rough check that a string names a subject rather than a greeting.

    Deliberately conservative: it rejects only what is clearly not a subject.
    Anything uncertain passes, because blocking a real topic is worse than
    running one useless search.
    """
    t = text.strip()
    if len(t) < 3 or _GREETING_RE.match(t):
        return False
    words = re.findall(r"[a-z0-9']+", t.lower())
    return bool(words) and any(w not in _FILLER_WORDS for w in words)


if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
