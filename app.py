import io
import os
import secrets
import tempfile
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
from core.llm.client import generate, chat
from core.rag.retrieve import retrieve
from core.vision.image_handler import transcribe
from core.vision.step_checker import check_working
from diagram_shots import shot_messages
from sessionlog import log_turn, attachment_meta, list_sessions, session_turns
import pdftext
import users
import settings as _settings
from api_v1 import v1
from ratelimit import RateLimiter, SlidingWindowLimiter

from core.prompts import (
    build_check_prompt, tutor_reply as _tutor_reply,
    TUTOR_SYSTEM_PROMPT, hint_note,
)
load_dotenv()

app = Flask(__name__, static_folder="static")



users.init()
app.register_blueprint(v1)



users.purge_expired()


@app.errorhandler(Exception)
def _unhandled_exception(e):
    app.logger.exception(e)
    if isinstance(e, ConnectionError):
        return jsonify({"error": "Could not reach the model. Is Ollama running?"}), 503
    return jsonify({"error": "Something went wrong on our end."}), 500

SESSION_COOKIE = "ollm_session"





COOKIE_SECURE = os.environ.get("OLLM_HTTPS", "").strip().lower() in {"1", "true", "yes"}




_login_limiter = RateLimiter(max_failures=8, window_seconds=15 * 60)

# Per-curriculum ingest state. Lives in process memory — resets on restart.
# {"sat-alevel": {"state": "idle"|"running"|"error", "chunks": N}}
_INGEST_STATUS: dict = {}

# 20 LLM calls per user per minute — generous for a real lesson, blocks bots.
_llm_limiter = SlidingWindowLimiter(max_calls=20, window_seconds=60)


def _check_llm_rate() -> object:
    """Return a 429 response if the current user is over the LLM call limit, else None."""
    if not _settings.load()["rate_limiting"]:
        return None
    key = f"user:{g.user['id']}"
    wait = _llm_limiter.check_and_record(key)
    if wait:
        resp = jsonify({"error": "Too many requests. Slow down and try again shortly."})
        resp.headers["Retry-After"] = str(wait)
        return resp, 429
    return None


def _login_keys(username: str) -> tuple:
    """The two buckets a login attempt counts against.

    IP alone is not enough — an attacker with a pool of addresses would get 8
    tries each against one account. Username alone is not enough either, or one
    machine could work through a list of accounts unhindered.
    """
    return (f"ip:{request.remote_addr}",
            f"user:{(username or '').strip().lower()}")




_OPEN_ENDPOINTS = {"index", "static", "api_register", "api_login",
                   "api_logout", "api_me", "admin_panel", "teacher_panel",
                   "dev_panel", "api_dev_get_settings", "api_dev_put_settings"}


_DEV_USER = {"id": 1, "username": "dev", "role": "admin"}

@app.before_request
def _load_user():
    """Turn the session cookie into g.user, and refuse anonymous callers."""
    cfg = _settings.load()
    dev_env = os.environ.get("DEV_BYPASS_AUTH", "").lower() in {"1", "true", "yes"}
    if dev_env or not cfg["auth_required"]:
        g.user = _DEV_USER
        return None
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
        httponly=True,          
        samesite="Lax",
        secure=COOKIE_SECURE,   
    )
    return resp


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.json or {}

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
        resp = jsonify({"error": "Too many failed logins. Try again later."})
        resp.headers["Retry-After"] = str(wait)
        return resp, 429

    uid = users.authenticate(data.get("username", ""), data.get("password", ""))
    if uid is None:
        _login_limiter.record_failure(*keys)
        return jsonify({"error": "Wrong username or password."}), 401

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
    return jsonify({"user": g.user})  # now includes role


def _key(data: dict, field: str, env_var: str) -> str:
    """A key typed into the UI wins; otherwise fall back to the one in .env."""
    return (data.get(field) or "").strip() or os.environ.get(env_var, "").strip()


def _curriculum_params(data: dict) -> tuple[str, str]:
    """Return (system_prompt, collection_name) for the curriculum in the request.

    Falls back to the default SAT/A-level prompt and 'reference' collection when
    no curriculum_id is supplied or the manifest can't be loaded.
    """
    cid = (data.get("curriculum_id") or "").strip()
    if cid:
        try:
            manifest = _cur.load(cid)
            from core.prompts import build_tutor_prompt
            prompt = build_tutor_prompt(flavour=manifest["prompt_flavour"])
            collection = manifest.get("collection", "reference")
            return prompt, collection
        except Exception:
            pass
    return TUTOR_SYSTEM_PROMPT, "reference"

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





_GRAPH_ALLOWED_NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.For, ast.If, ast.Pass,
    ast.Call, ast.keyword, ast.Name, ast.Attribute, ast.Subscript, ast.Slice, ast.Starred,
    ast.Constant, ast.Tuple, ast.List, ast.Dict, ast.Set,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context,
)


_GRAPH_BANNED_ATTRS = {"savefig", "show", "close", "imsave"}



_GRAPH_BANNED_NAMES = {
    "exec", "eval", "compile", "open", "input", "breakpoint", "help",
    "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr",
}



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






_LITERAL_DATA_MIN = 4


def _has_literal_data(code: str) -> bool:
    """True if the code plots a hardcoded run of numbers rather than computing them."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            numbers = [e for e in node.elts
                       if isinstance(e, ast.Constant)
                       and isinstance(e.value, (int, float))
                       and not isinstance(e.value, bool)]
            if len(numbers) >= _LITERAL_DATA_MIN:
                return True
    return False


ALLOWED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PDF_TEXT_LIMIT  = 8000



PAPER_CACHE_DIR = Path(__file__).parent / "data" / "papers"
PAPER_MAX_BYTES = 20 * 1024 * 1024   
PAPER_MAX_FETCH = 3                  
VERIFY_OVERSHOOT = 3                 
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
    resp = send_from_directory("static", "index.html")
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/favicon.ico")
def favicon():
    return "", 204



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



@app.route("/api/graph", methods=["POST"])
def api_graph():
    err = _check_llm_rate()
    if err: return err
    data        = request.json
    description = data.get("description", "")
    provider    = data.get("provider", "ollama")
    model       = data.get("model", "gemma4")
    host        = data.get("host", "http://localhost:11434")
    api_key     = _key(data, "api_key", "API_KEY")

    if not description:
        return jsonify({"error": "No description provided"}), 400

    messages = [{"role": "system", "content": GRAPH_SYSTEM_PROMPT}]
    messages += shot_messages(description)     
    messages.append({"role": "user",
                     "content": f"Generate a graph for: {description}"})
    raw_code = chat(messages, model=model, host=host, provider=provider, api_key=api_key)

    if "NEED_REAL_DATA" in raw_code:
        return jsonify({"error": "That graph needs real data I do not have. "
                                 "Give me the figures and I will plot them, or "
                                 "ask for a diagram that shows the shape of the "
                                 "relationship instead."}), 400

    code = re.sub(r"^```(?:python)?\n?", "", raw_code.strip())
    code = re.sub(r"\n?```$", "", code)
    code = re.sub(r"plt\.(savefig|show|close)\(.*?\)\n?", "", code)
    code = re.sub(r"^\s*(?:import|from)\s+.*$", "", code, flags=re.MULTILINE)

    err = _check_graph_code(code)
    if err:
        return jsonify({"error": f"Refused to run the generated graph code — {err}"}), 400

    try:
        plt.close("all")
        exec(code, {"__builtins__": _GRAPH_BUILTINS, "plt": plt, "np": np})  
        if _has_literal_data(code):
            plt.gcf().text(0.99, 0.01, "Illustrative — values are not real data",
                           ha="right", va="bottom", fontsize=7, color="#b45309")
        return jsonify({"image": _render_png()})
    except Exception as e:
        plt.close("all")
        return jsonify({"error": str(e)}), 500



@app.route("/api/start", methods=["POST"])
def api_start():
    err = _check_llm_rate()
    if err: return err
    data       = request.json
    topic      = data.get("topic", "")
    provider   = data.get("provider", "ollama")
    model      = data.get("model", "gemma4")
    host       = data.get("host", "http://localhost:11434")
    api_key      = _key(data, "api_key", "API_KEY")
    attachment   = data.get("attachment")
    vision_model = data.get("vision_model", "")

    system_prompt, collection = _curriculum_params(data)

    cid = (data.get("curriculum_id") or "").strip()
    if cid:
        q_path = Path("curricula") / cid / "questions.json"
        if q_path.exists():
            try:
                qs = json.loads(q_path.read_text(encoding="utf-8"))
                if qs:
                    q_lines = []
                    for q in qs[:20]:
                        line = "- " + (q.get("text") or q.get("question") or "").strip()
                        if q.get("answer"):
                            line += f" [answer: {q['answer'].strip()}]"
                        if line.strip() != "-":
                            q_lines.append(line)
                    if q_lines:
                        system_prompt += (
                            "\n\nQuestion bank for this curriculum (use these when "
                            "quizzing the student — present them one at a time, never "
                            "reveal the answer until the student has attempted it):\n"
                            + "\n".join(q_lines)
                        )
            except Exception:
                pass

    context_chunks = retrieve(topic, collection_name=collection)
    context        = "\n\n".join(context_chunks) if context_chunks else ""
    context_prefix = f"Reference material:\n{context}\n\n" if context else ""

    user_msg = {"role": "user", "content": f"{context_prefix}Teach me about: {topic}"}
    if attachment:
        _apply_attachment(user_msg, attachment, provider, model, host, api_key, vision_model)

    messages = [{"role": "system", "content": system_prompt}, user_msg]
    started  = time.monotonic()
    raw = chat(messages, model=model, host=host, provider=provider, api_key=api_key)
    response, _ = _tutor_reply(raw)
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
    err = _check_llm_rate()
    if err: return err
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
    _, collection = _curriculum_params(data)

    if _mentions_papers(user_input):
        started = time.monotonic()
        intent = _paper_intent(user_input, topic, model=model, host=host,
                               provider=provider, api_key=api_key)
        if intent["wants_papers"]:
            reply, papers = _papers_for_chat(intent["topic"], tavily_key)
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": reply})
            log_turn("papers",
                     session_id=data.get("session_id", ""),
                     user_id=g.user["id"],
                     mode="learn", topic=intent["topic"] or topic,
                     provider=provider, model=model,
                     input=user_input, output=reply,
                     correct=None, wrong_streak=wrong_streak,
                     attachment=attachment_meta(attachment),
                     tokens={},          
                     latency_ms=round((time.monotonic() - started) * 1000))
            return jsonify({
                "response": reply,
                "messages": _strip_images(messages),
                "done": False,
                "correct": None,
                "papers": papers,
            })

    user_msg = {"role": "user", "content": user_input + hint_note(wrong_streak)}
    if attachment:
        _apply_attachment(user_msg, attachment, provider, model, host, api_key, vision_model)

    messages.append(user_msg)
    started = time.monotonic()
    raw = chat(messages, model=model, host=host, provider=provider, api_key=api_key)
    response, correct = _tutor_reply(raw)
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

    cid = (data.get("curriculum_id") or "").strip()
    if correct is not None and g.user and cid and topic:
        users.record_progress(g.user["id"], cid, topic, correct)

    return jsonify({
        "response": response,
        "messages": _strip_images(messages),
        "done": "Topic complete." in response,
        "correct": correct,
    })
    



_SESSION_ID_MAX = 64

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
        return jsonify({"error": "no such session"}), 404

    lesson = [t for t in turns if t.get("event") in _REPLAYABLE]
    shown  = lesson or turns            

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



@app.route("/api/check", methods=["POST"])
def api_check():
    err = _check_llm_rate()
    if err: return err
    data       = request.json
    question   = data.get("question", "")
    answer     = data.get("answer", "")
    provider   = data.get("provider", "ollama")
    model      = data.get("model", "gemma4")
    host       = data.get("host", "http://localhost:11434")
    api_key      = _key(data, "api_key", "API_KEY")
    attachment   = data.get("attachment")
    vision_model = data.get("vision_model", "")

    system_prompt, collection = _curriculum_params(data)
    context_chunks = retrieve(question, collection_name=collection)
    context        = "\n\n".join(context_chunks) if context_chunks else ""
    context_prefix = f"Reference material:\n{context}\n\n" if context else ""

    if attachment and attachment.get("type") == "image" and provider == "ollama":
        messages = [
            {"role": "system", "content": system_prompt},
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
        response, correct = _tutor_reply(raw)
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

    image_context = ""
    if attachment and attachment.get("type") == "image":
        image_context = _transcription_note(attachment, provider, model, host, api_key, vision_model).strip() + "\n\n"

    prompt   = build_check_prompt(
        question, answer, context_prefix=f"{context_prefix}{pdf_context}{image_context}")
    started  = time.monotonic()
    raw      = generate(prompt, model=model, host=host, provider=provider, api_key=api_key)
    response, correct = _tutor_reply(raw)
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



@app.route("/api/check_working", methods=["POST"])
def api_check_working():
    """Transcribe handwritten working line by line and locate the first wrong step."""
    err = _check_llm_rate()
    if err: return err
    data         = request.json or {}
    b64          = data.get("b64", "")
    provider     = data.get("provider", "ollama")
    model        = data.get("model", "gemma4")
    host         = data.get("host", "http://localhost:11434")
    api_key      = _key(data, "api_key", "API_KEY")
    vision_model = data.get("vision_model", "")

    if not b64:
        return jsonify({"error": "no image provided"}), 400

    img_bytes = base64.b64decode(b64)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(img_bytes)
        tmp_path = f.name

    try:
        started = time.monotonic()
        result  = check_working(tmp_path, provider=provider, model=model,
                                host=host, api_key=api_key,
                                vision_model=vision_model)
        latency = round((time.monotonic() - started) * 1000)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    log_turn("check_working",
             session_id=data.get("session_id", ""),
             user_id=g.user["id"],
             provider=provider, model=model,
             steps=len(result["steps"]),
             error_index=result["error_index"],
             latency_ms=latency)

    return jsonify(result)


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


def _ai_evaluate(student_input: str, tutor_reply: str, **llm) -> bool | None:
    """Fallback evaluator when the tutor reply has no [CORRECT]/[WRONG] signal.

    Makes one cheap call asking the model to judge based on the tutor's own
    wording — if the tutor sounds affirming, it's correct; if it sounds
    corrective, it's wrong. Returns None on any failure so callers stay
    fail-open.
    """
    msgs = [{"role": "user", "content": (
        f"A tutor responded to a student.\n\n"
        f"Student said: {student_input}\n\n"
        f"Tutor replied: {tutor_reply}\n\n"
        "Based only on the tutor's reply, was the student's answer correct? "
        "Reply with exactly one word: CORRECT or WRONG."
    )}]
    try:
        r = chat(msgs, **llm)
        upper = str(r).upper()
        if "CORRECT" in upper: return True
        if "WRONG"   in upper: return False
    except Exception:
        pass
    return None


_NUMERIC_RE = re.compile(r'\d')

_FILLER_RE = re.compile(
    r'\b(is\s+(it|this(\s+the\s+answer)?|that\s+(right|correct))|'
    r'i\s+think\s+(it\'?s?|the\s+answer\s+is)|'
    r'the\s+answer\s+is|would\s+it\s+be|so\s+it\'?s?)\b.*$',
    re.IGNORECASE
)

def _extract_math(text: str) -> str:
    """Strip English filler to isolate the mathematical expression."""
    cleaned = _FILLER_RE.sub('', text).strip().strip(',').strip()
    return cleaned if cleaned else text.strip()

def _verify_math(student_input: str, messages: list, **llm) -> bool | None:
    """Independently re-solves when tutor marks a numeric answer correct.
    Never sees the tutor's verdict — solves from scratch to avoid agreeing blindly.
    """
    question = next(
        (m["content"] for m in reversed(messages) if m["role"] == "assistant"),
        ""
    )
    prompt = (
        f"A student answered this maths question:\n{question}\n\n"
        f"Their answer: {student_input}\n\n"
        "Solve it yourself from scratch. Ignore what anyone else said. "
        "Is the student's answer correct? Reply with exactly one word: VERIFIED or WRONG."
    )
    try:
        r = chat([{"role": "user", "content": prompt}], **llm)
        upper = str(r).upper()
        if "VERIFIED" in upper: return True
        if "WRONG"   in upper: return False
    except Exception:
        pass
    return None


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
    (PAPER_CACHE_DIR / f"{paper_id}.json").write_text(
        json.dumps({"url": url, "title": title}))
    return paper_id


@app.route("/api/papers/download/<paper_id>")
def api_paper_download(paper_id: str):
    if not _PAPER_ID_RE.match(paper_id):
        return jsonify({"error": "Bad paper id"}), 400

    pdf_path = PAPER_CACHE_DIR / f"{paper_id}.pdf"
    if not pdf_path.is_file():
        return jsonify({"error": "Paper not in cache — run the search again"}), 404

    meta_path = PAPER_CACHE_DIR / f"{paper_id}.json"
    title = json.loads(meta_path.read_text()).get("title", "") if meta_path.is_file() else ""
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
        return questions, 0

    tail = reply.rsplit("FINAL", 1)[-1]
    verdicts = {int(n): letter.upper() for n, letter in _VERDICT_RE.findall(tail)}

    kept = []
    for i, q in enumerate(questions, 1):
        verdict = verdicts.get(i)
        if verdict is None or verdict == q["answer"]:
            kept.append(q)
    return kept, len(questions) - len(kept)


@app.route("/api/papers", methods=["POST"])
def api_papers():
    err = _check_llm_rate()
    if err: return err
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

    papers, paper_texts = _collect_papers(results)

    if paper_texts:
        combined = "\n\n---\n\n".join(paper_texts)[:7000]
    else:
        content_parts = [r["content"] for r in results[:5] if r.get("content")]
        combined = "\n\n---\n\n".join(content_parts)[:7000]

    sources = [{"title": r.get("title", ""), "url": r.get("url", "")} for r in results[:5]]

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
    response, _ = _tutor_reply(response)
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















_PAPER_NOUN = r"(?:past[\s-]?papers?|exam papers?|pdfs?|mark schemes?|real (?:exam )?questions?|papers)"
_FETCH_VERB = r"(?:get|give|fetch|find|download|send|show|grab|take|provide|need|want|have)"
_NEGATION   = r"(?:don'?t|do not|not|no need|nope|never|rather not|without)"
_ABOUT_RE = re.compile(r"^\s*(?:what|why|how|explain|describe|tell me about)\b", re.IGNORECASE)


_WANTS_PAPERS_RE = re.compile(
    rf"\b{_FETCH_VERB}\b[^.?!]{{0,40}}?\b{_PAPER_NOUN}\b", re.IGNORECASE)

_NOT_PAPERS_RE = re.compile(
    rf"\b{_NEGATION}\b[^.?!]{{0,40}}?\b{_PAPER_NOUN}\b", re.IGNORECASE)


def _wants_papers(text: str) -> bool:
    """True when the student is asking for actual paper files."""
    if not text or _NOT_PAPERS_RE.search(text):
        return False
    if _WANTS_PAPERS_RE.search(text):
        return True
    if _ABOUT_RE.search(text):
        return False
    return len(text.split()) <= 8 and bool(re.search(_PAPER_NOUN, text, re.I))



_TOPIC_IN_REQUEST_RE = re.compile(
    rf"{_PAPER_NOUN}\s+(?:on|for|about|in)\s+([a-z0-9][a-z0-9 '\-]{{2,50}})", re.IGNORECASE)



_TOPIC_TRAIL_RE = re.compile(r"\b(?:please|pls|thanks|thank you|now|asap|ok)\b\s*$", re.IGNORECASE)


def _stated_topic(user_input: str) -> str:
    """The subject named in the request itself, or empty."""
    m = _TOPIC_IN_REQUEST_RE.search(user_input)
    return _TOPIC_TRAIL_RE.sub("", m.group(1)).strip() if m else ""












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

    if not isinstance(data.get("wants_papers"), bool):
        return fallback

    topic = data.get("topic")
    topic = topic.strip() if isinstance(topic, str) else ""
    return {"wants_papers": data["wants_papers"], "topic": topic}






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
import curricula as _cur


@app.route("/api/curricula")
def api_student_curricula():
    """List curricula available to students (requires login only)."""
    if g.user is None:
        return jsonify({"error": "Not logged in"}), 401
    cfg = _settings.load()
    result = []
    for cid in _cur.list_curricula():
        if cid == "demo" and not cfg["stub_testing"]:
            continue
        try:
            m = _cur.load(cid)
            result.append({
                "id":      cid,
                "name":    m.get("name", cid),
                "level":   m.get("level", ""),
                "subjects": m.get("subjects", []),
            })
        except Exception:
            result.append({"id": cid, "name": cid, "level": "", "subjects": []})
    return jsonify(result)

@app.route("/api/curricula/<cid>/questions")
def api_student_questions(cid):
    if g.user is None:
        return jsonify({"error": "Not logged in"}), 401
    path = Path("curricula") / cid / "questions.json"
    if not path.exists():
        return jsonify([])
    return jsonify(json.loads(path.read_text(encoding="utf-8")))
@app.route("/api/curricula/<cid>/questions", methods=["POST"])
def api_student_questions_add(cid):
    if g.user is None:
        return jsonify({"error": "Not logged in"}), 401
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    path = Path("curricula") / cid / "questions.json"
    questions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    q = {
        "id":     secrets.token_hex(8),
        "text":   text,
        "answer": (data.get("answer") or "").strip(),
        "marks":  1,
        "image":  (data.get("image") or ""),
        "author": g.user["username"],
    }
    questions.append(q)
    path.write_text(json.dumps(questions, indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonify(q), 201
@app.route("/api/curricula/<cid>/info")
def api_student_curriculum_info(cid):
    if g.user is None:
        return jsonify({"error": "Not logged in"}), 401
    try:
        manifest = _cur.load(cid)
    except FileNotFoundError:
        return jsonify({"error": "Not found"}), 404
    topics_path = Path("curricula") / cid / "topics.json"
    topics = json.loads(topics_path.read_text(encoding="utf-8")) if topics_path.exists() else []
    return jsonify({"manifest": manifest, "topics": topics})


@app.route("/api/progress/<cid>")
def api_get_progress(cid):
    if g.user is None:
        return jsonify({"error": "Not logged in"}), 401
    return jsonify(users.get_progress(g.user["id"], cid))


@app.route("/api/teacher/curricula/<cid>/progress")
def api_teacher_progress(cid):
    err = _teacher_or_admin()
    if err: return err
    return jsonify(users.get_all_progress(cid))


@app.route("/api/curricula/<cid>/materials")
def api_student_materials(cid):
    """List uploaded files for any logged-in student."""
    if g.user is None:
        return jsonify({"error": "Not logged in"}), 401
    ref_dir = Path("curricula") / cid / "reference"
    if not ref_dir.exists():
        return jsonify([])
    files = [
        {"name": f.name, "url": f"/api/curricula/{cid}/materials/{f.name}"}
        for f in sorted(ref_dir.iterdir()) if f.is_file()
    ]
    return jsonify(files)


@app.route("/api/curricula/<cid>/materials/<filename>")
def api_student_material_file(cid, filename):
    if g.user is None:
        return jsonify({"error": "Not logged in"}), 401
    ref_dir = Path("curricula") / cid / "reference"
    return send_from_directory(ref_dir.resolve(), secure_filename(filename))
@app.route("/api/admin/curricula/<cid>/auto-research", methods=["POST"])
def api_admin_auto_research(cid):
    err = _admin_only()
    if err:
        return err
    try:
        manifest = _cur.load(cid)
    except FileNotFoundError:
        return jsonify({"error": "Curriculum not found"}), 404
    tavily_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not tavily_key:
        return jsonify({"error": "TAVILY_API_KEY not set in .env"}), 400
    api_key = os.environ.get("API_KEY", "").strip()
    name     = manifest.get("name", cid)
    flavour  = manifest.get("prompt_flavour", name)
    subjects = manifest.get("subjects", [])
    queries  = [
        f"{name} curriculum overview objectives",
        f"{name} topics syllabus structure",
    ]
    for subj in subjects[:3]:
        queries.append(f"{name} {subj} key concepts")

    snippets = []
    for q in queries:
        try:
            res = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": tavily_key, "query": q,
                      "search_depth": "basic", "max_results": 4},
                timeout=15,
            )
            if res.ok:
                for r in res.json().get("results", []):
                    content = (r.get("content") or "").strip()
                    if content:
                        snippets.append(f"[{r.get('title','')}]\n{content}")
        except Exception:
            pass

    if not snippets:
        return jsonify({"error": "No search results returned"}), 502

    combined = "\n\n---\n\n".join(snippets)
    synthesis_prompt = (
        f"You are writing reference notes for a tutor AI that teaches {flavour}. "
        f"Using only the search results below, write clear structured notes covering: "
        f"overview, main topics, key concepts, and learning objectives. "
        f"Use plain English. Use markdown headings. Do not invent facts not in the sources.\n\n"
        f"Search results:\n{combined[:12000]}"
    )
    try:
        notes = generate(
            synthesis_prompt,
            model="openai/gpt-oss-120b",
            provider="groq",
            api_key=api_key,
        )
    except Exception as e:
        return jsonify({"error": f"LLM synthesis failed: {e}"}), 502

    ref_dir = Path("curricula") / cid / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)
    (ref_dir / "auto-research.txt").write_text(notes, encoding="utf-8")

    import subprocess
    subprocess.Popen(
        ["python", "-m", "rag.ingest", "--curriculum", cid],
        cwd=Path(__file__).parent,
    )
    return jsonify({"ok": True, "notes_length": len(notes),
                    "queries": queries, "snippets_found": len(snippets)})
# ── Teacher panel ─────────────────────────────────────────────────────────────

_TEACHER_ALLOWED_EXT = {".pdf", ".txt", ".pptx"}
_TEACHER_MAX_BYTES   = 32 * 1024 * 1024   # 32 MB


def _teacher_or_admin():
    return _require_role("teacher", "admin")


def _resolve_ref_dir(manifest: dict) -> Path:
    """Absolute path to the curriculum's reference directory."""
    ref = _cur.reference_dir(manifest)
    p = Path(ref) if Path(ref).is_absolute() else Path(__file__).parent / ref
    p.mkdir(parents=True, exist_ok=True)
    return p


def _extract_pptx(data: bytes) -> str:
    """Pull all text out of a PowerPoint file."""
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                parts.append(shape.text.strip())
    return "\n\n".join(parts)


def _questions_path(cid: str) -> Path:
    return _cur.CURRICULA_DIR / cid / "questions.json"


def _load_questions(cid: str) -> list:
    p = _questions_path(cid)
    return json.loads(p.read_text()) if p.exists() else []


def _save_questions(cid: str, questions: list) -> None:
    _questions_path(cid).write_text(json.dumps(questions, indent=2, ensure_ascii=False))


@app.route("/teacher")
def teacher_panel():
    return send_from_directory("static", "teacher.html")


@app.route("/api/teacher/curricula")
def api_teacher_curricula():
    err = _teacher_or_admin()
    if err: return err
    result = []
    for cid in _cur.list_curricula():
        try:
            m = _cur.load(cid)
            result.append({"id": cid, "name": m.get("name", cid)})
        except Exception:
            result.append({"id": cid, "name": cid})
    return jsonify(result)


@app.route("/api/teacher/curricula/<cid>")
def api_teacher_get(cid):
    err = _teacher_or_admin()
    if err: return err
    try:
        manifest = _cur.load(cid)
    except FileNotFoundError:
        return jsonify({"error": "not found"}), 404

    topics_path = _cur.CURRICULA_DIR / cid / "topics.json"
    topics = json.loads(topics_path.read_text()) if topics_path.exists() else []

    ref_dir = _resolve_ref_dir(manifest)
    files = sorted(
        {"name": f.name, "size": f.stat().st_size, "ext": f.suffix.lower()}
        for f in ref_dir.iterdir() if f.is_file()
    )

    questions = _load_questions(cid)

    return jsonify({
        "manifest": {"id": manifest["id"], "name": manifest["name"]},
        "topics": topics,
        "files": files,
        "question_count": len(questions),
    })


@app.route("/api/teacher/curricula/<cid>/topics", methods=["PUT"])
def api_teacher_save_topics(cid):
    err = _teacher_or_admin()
    if err: return err
    try:
        _cur.load(cid)
    except FileNotFoundError:
        return jsonify({"error": "not found"}), 404
    topics = request.json if isinstance(request.json, list) else []
    topics_path = _cur.CURRICULA_DIR / cid / "topics.json"
    topics_path.write_text(json.dumps(topics, indent=2, ensure_ascii=False))
    return jsonify({"ok": True})


@app.route("/api/teacher/curricula/<cid>/upload", methods=["POST"])
def api_teacher_upload(cid):
    err = _teacher_or_admin()
    if err: return err
    try:
        manifest = _cur.load(cid)
    except FileNotFoundError:
        return jsonify({"error": "not found"}), 404

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "no file"}), 400

    filename = secure_filename(file.filename or "upload")
    ext = Path(filename).suffix.lower()
    if ext not in _TEACHER_ALLOWED_EXT:
        return jsonify({"error": f"Allowed types: {', '.join(_TEACHER_ALLOWED_EXT)}"}), 400

    data = file.read()
    if len(data) > _TEACHER_MAX_BYTES:
        return jsonify({"error": "File too large (max 32 MB)"}), 413

    ref_dir = _resolve_ref_dir(manifest)

    if ext == ".pptx":
        text = _extract_pptx(data)
        if not text.strip():
            return jsonify({"error": "No readable text found in PowerPoint"}), 400
        save_name = Path(filename).stem + ".txt"
        (ref_dir / save_name).write_text(text, encoding="utf-8")
    else:
        (ref_dir / filename).write_bytes(data)
        save_name = filename

    _start_ingest(cid, manifest)
    return jsonify({"ok": True, "saved_as": save_name})


@app.route("/api/teacher/curricula/<cid>/files")
def api_teacher_files(cid):
    err = _teacher_or_admin()
    if err: return err
    try:
        manifest = _cur.load(cid)
    except FileNotFoundError:
        return jsonify({"error": "not found"}), 404
    ref_dir = _resolve_ref_dir(manifest)
    files = sorted(
        {"name": f.name, "size": f.stat().st_size}
        for f in ref_dir.iterdir() if f.is_file()
    )
    return jsonify(files)


@app.route("/api/teacher/curricula/<cid>/files/<filename>", methods=["DELETE"])
def api_teacher_delete_file(cid, filename):
    err = _teacher_or_admin()
    if err: return err
    try:
        manifest = _cur.load(cid)
    except FileNotFoundError:
        return jsonify({"error": "not found"}), 404
    safe = secure_filename(filename)
    target = _resolve_ref_dir(manifest) / safe
    if not target.exists():
        return jsonify({"error": "file not found"}), 404
    target.unlink()
    return jsonify({"ok": True})


@app.route("/api/teacher/curricula/<cid>/questions")
def api_teacher_questions(cid):
    err = _teacher_or_admin()
    if err: return err
    if not (_cur.CURRICULA_DIR / cid / "manifest.json").exists():
        return jsonify({"error": "not found"}), 404
    return jsonify(_load_questions(cid))


@app.route("/api/teacher/curricula/<cid>/questions", methods=["POST"])
def api_teacher_add_question(cid):
    err = _teacher_or_admin()
    if err: return err
    if not (_cur.CURRICULA_DIR / cid / "manifest.json").exists():
        return jsonify({"error": "not found"}), 404
    data = request.json or {}
    q_text = (data.get("question") or "").strip()
    answer = (data.get("answer") or "").strip()
    if not q_text or not answer:
        return jsonify({"error": "question and answer required"}), 400
    questions = _load_questions(cid)
    new_q = {
        "id": secrets.token_hex(8),
        "topic": (data.get("topic") or "").strip(),
        "question": q_text,
        "answer": answer,
        "type": data.get("type", "short_answer"),
        "created_by": g.user["id"],
        "created_at": int(time.time()),
    }
    questions.append(new_q)
    _save_questions(cid, questions)
    return jsonify(new_q), 201


@app.route("/api/teacher/curricula/<cid>/questions/<qid>", methods=["DELETE"])
def api_teacher_delete_question(cid, qid):
    err = _teacher_or_admin()
    if err: return err
    questions = _load_questions(cid)
    questions = [q for q in questions if q.get("id") != qid]
    _save_questions(cid, questions)
    return jsonify({"ok": True})


def _start_ingest(cid: str, manifest: dict) -> bool:
    """Kick off a background ingest for `cid`. Returns False if already running."""
    import threading
    from core.rag.ingest import build
    if _INGEST_STATUS.get(cid, {}).get("state") == "running":
        return False
    _INGEST_STATUS[cid] = {"state": "running", "chunks": 0}

    def _run():
        try:
            n = build(text_folder=_cur.reference_dir(manifest),
                      pdf_folder=_cur.papers_dir(manifest),
                      collection_name=manifest["collection"])
            _INGEST_STATUS[cid] = {"state": "idle", "chunks": n}
        except Exception as exc:
            app.logger.error("Ingest failed for %s: %s", cid, exc)
            _INGEST_STATUS[cid] = {"state": "error", "chunks": 0}

    threading.Thread(target=_run, daemon=True).start()
    return True


@app.route("/api/teacher/curricula/<cid>/ingest", methods=["GET", "POST"])
def api_teacher_ingest(cid):
    err = _teacher_or_admin()
    if err: return err
    if request.method == "GET":
        return jsonify(_INGEST_STATUS.get(cid, {"state": "idle", "chunks": 0}))
    try:
        manifest = _cur.load(cid)
    except FileNotFoundError:
        return jsonify({"error": "not found"}), 404
    started = _start_ingest(cid, manifest)
    return jsonify({"ok": True, "already_running": not started})


# ── Admin panel ───────────────────────────────────────────────────────────────


def _require_role(*roles):
    """Return a 401/403 response if the current user lacks one of the given roles."""
    if g.user is None:
        return jsonify({"error": "Not logged in"}), 401
    if g.user.get("role") not in roles:
        return jsonify({"error": "Insufficient permissions"}), 403
    return None


def _admin_only():
    return _require_role("admin")


@app.route("/admin")
def admin_panel():
    return send_from_directory("static", "admin.html")


@app.route("/api/admin/curricula")
def api_admin_list():
    err = _admin_only()
    if err:
        return err
    result = []
    for cid in _cur.list_curricula():
        try:
            m = _cur.load(cid)
            result.append({"id": cid, "name": m.get("name", cid)})
        except Exception:
            result.append({"id": cid, "name": cid})
    return jsonify(result)


@app.route("/api/admin/curricula/<cid>", methods=["GET"])
def api_admin_get(cid):
    err = _admin_only()
    if err:
        return err
    try:
        manifest = _cur.load(cid)
    except FileNotFoundError:
        return jsonify({"error": "not found"}), 404
    topics_path = _cur.CURRICULA_DIR / cid / "topics.json"
    topics = json.loads(topics_path.read_text()) if topics_path.exists() else []
    return jsonify({"manifest": manifest, "topics": topics})


@app.route("/api/admin/curricula/<cid>", methods=["PUT"])
def api_admin_save(cid):
    err = _admin_only()
    if err:
        return err
    data = request.json or {}
    manifest_path = _cur.CURRICULA_DIR / cid / "manifest.json"
    if not manifest_path.exists():
        return jsonify({"error": "not found"}), 404
    manifest = json.loads(manifest_path.read_text())
    for field in ("name", "prompt_flavour", "collection",
                  "reference_dir", "papers_dir", "level", "subjects"):
        if field in data:
            manifest[field] = data[field]
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    if "topics" in data:
        topics_path = _cur.CURRICULA_DIR / cid / "topics.json"
        topics_path.write_text(json.dumps(data["topics"], indent=2, ensure_ascii=False))
    return jsonify({"ok": True})


@app.route("/api/admin/curricula", methods=["POST"])
def api_admin_create():
    err = _admin_only()
    if err:
        return err
    data = request.json or {}
    cid = re.sub(r"[^a-z0-9-]", "-", (data.get("id") or "").lower().strip())
    if not cid:
        return jsonify({"error": "id required"}), 400
    new_dir = _cur.CURRICULA_DIR / cid
    if new_dir.exists():
        return jsonify({"error": "already exists"}), 409
    (new_dir / "reference").mkdir(parents=True)
    (new_dir / "papers").mkdir(parents=True)
    manifest = {
        "id": cid,
        "name": data.get("name", cid),
        "prompt_flavour": data.get("prompt_flavour",
                                   f"{data.get('name', cid)} exam preparation"),
        "collection": cid.replace("-", "_"),
        "reference_dir": f"curricula/{cid}/reference",
        "papers_dir": f"curricula/{cid}/papers",
    }
    (new_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (new_dir / "topics.json").write_text("[]")
    return jsonify(manifest), 201


@app.route("/api/admin/curricula/<cid>/ingest", methods=["GET", "POST"])
def api_admin_ingest(cid):
    err = _admin_only()
    if err:
        return err
    if request.method == "GET":
        return jsonify(_INGEST_STATUS.get(cid, {"state": "idle", "chunks": 0}))
    try:
        manifest = _cur.load(cid)
    except FileNotFoundError:
        return jsonify({"error": "not found"}), 404
    started = _start_ingest(cid, manifest)
    return jsonify({"ok": True, "already_running": not started})


@app.route("/api/admin/curricula/<cid>/import-paper-questions", methods=["POST"])
def api_admin_import_paper_questions(cid):
    err = _admin_only()
    if err:
        return err
    import io
    from pypdf import PdfReader
    data    = request.get_json(force=True) or {}
    url     = (data.get("url") or "").strip()
    api_key = _key(data, "api_key", "API_KEY")
    model   = (data.get("model") or "gemma4").strip()
    if not url:
        return jsonify({"error": "url required"}), 400
    if not _allowed_paper_host(url):
        return jsonify({"error": "Domain not in allowlist"}), 403
    pdf_bytes = _fetch_pdf(url)
    if not pdf_bytes:
        return jsonify({"error": "Could not fetch PDF"}), 502

    reader    = PdfReader(io.BytesIO(pdf_bytes))
    pages     = [page.extract_text() or "" for page in reader.pages]
    full_text = "\n\n".join(pages)
    if len(full_text.strip()) < 100:
        return jsonify({"error": "Could not extract text from PDF — may be scanned or maths-heavy"}), 422

    extract_prompt = (
        "Output valid JSON only — no prose, no markdown fences.\n\n"
        "You are given raw text from an exam past paper. "
        "Extract every question. Copy each question verbatim. "
        "If a question has numerical values or named variables "
        "(dates, quantities, percentages), change them to different "
        "plausible values so the question is fresh but structurally identical. "
        "Ignore cover pages, rubrics, instructions, and mark allocations. "
        'Return a JSON array. Each element: {"question": "...", "answer": null}. '
        "If a mark scheme is present in the text, populate answer.\n\n"
        f"PAPER TEXT:\n{full_text[:14000]}"
    )

    raw = generate(extract_prompt, model=model, api_key=api_key, provider="groq")
    m   = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return jsonify({"error": "LLM did not return a JSON array"}), 500

    new_qs   = json.loads(m.group())
    existing = json.loads(_questions_path(cid).read_text(encoding="utf-8")) \
               if _questions_path(cid).exists() else []
    existing.extend(new_qs)
    _save_questions(cid, existing)
    return jsonify({"ok": True, "imported": len(new_qs)})



@app.route("/api/admin/users")
def api_admin_users():
    err = _admin_only()
    if err:
        return err
    return jsonify(users.list_users())


@app.route("/api/admin/users/<int:uid>/role", methods=["PUT"])
def api_admin_set_role(uid: int):
    err = _admin_only()
    if err:
        return err
    role = (request.json or {}).get("role", "")
    if not role:
        return jsonify({"error": "role required"}), 400
    try:
        users.set_role(uid, role)
    except users.UserError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.route("/api/admin/api-keys")
def api_admin_list_keys():
    err = _admin_only()
    if err:
        return err
    return jsonify(users.list_api_keys(g.user["id"]))


@app.route("/api/admin/api-keys", methods=["POST"])
def api_admin_create_key():
    err = _admin_only()
    if err:
        return err
    label = ((request.json or {}).get("label") or "").strip()
    if not label:
        return jsonify({"error": "label required"}), 400
    token = users.create_api_key(g.user["id"], label)
    return jsonify({"token": token})


@app.route("/api/admin/api-keys/<int:key_id>", methods=["DELETE"])
def api_admin_revoke_key(key_id: int):
    err = _admin_only()
    if err:
        return err
    users.revoke_api_key(key_id, g.user["id"])
    return jsonify({"ok": True})


@app.route("/dev")
def dev_panel():
    return send_from_directory("static", "dev.html")


@app.route("/api/dev/settings")
def api_dev_get_settings():
    return jsonify(_settings.load())


@app.route("/api/dev/settings", methods=["PUT"])
def api_dev_put_settings():
    saved = _settings.save(request.get_json(force=True) or {})
    return jsonify(saved)


if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True, port=5000, use_reloader=False)
