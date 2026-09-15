import functools
import os
import tempfile
import json 
import curricula
from pathlib import Path
from flask import Blueprint, request, jsonify

import users
import settings as _settings
from ratelimit import SlidingWindowLimiter
import core.check
import core.tutor
import core.questions
import core.vision.step_checker

v1 = Blueprint("v1", __name__, url_prefix="/v1")
_v1_limiter = SlidingWindowLimiter(max_calls=20, window_seconds=60)


def _llm_kwargs() -> dict:
    """Pull model/provider/api_key/host from request JSON if provided."""
    body = request.get_json(silent=True) or {}
    out = {}
    for key in ("model", "provider", "api_key", "host"):
        if key in body:
            out[key] = body[key]
    return out


def _form_llm_kwargs(extra_keys=()) -> dict:
    """Same, but reads from multipart form fields (for file-upload endpoints)."""
    out = {}
    for key in ("model", "provider", "api_key", "host") + tuple(extra_keys):
        val = request.form.get(key)
        if val:
            out[key] = val
    return out


def _bearer_user():
    """Resolve the Bearer token to a user dict, or return None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return users.user_for_api_key(auth[7:])


def _over_limit(user_id: int):
    """A 429 response if this key owner is over the ceiling, else None."""
    if not _settings.load()["rate_limiting"]:
        return None
    wait = _v1_limiter.check_and_record(f"apikey-owner:{user_id}")
    if not wait:
        return None
    resp = jsonify({"error": "Too many requests. Slow down and try again shortly."})
    resp.headers["Retry-After"] = str(wait)
    return resp, 429


def require_auth(f):
    """Decorator: 401 without a valid Bearer token, 429 over the rate limit.

    The limit is checked here rather than on each route so a new /v1/
    endpoint cannot be added without one. Key management counts against the
    same bucket on purpose — minting keys in a loop is abuse too.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = _bearer_user()
        if user is None:
            return jsonify({"error": "Invalid or missing API key"}), 401
        limited = _over_limit(user["id"])
        if limited is not None:
            return limited
        request.api_user = user
        return f(*args, **kwargs)
    return wrapper


# ── ping ──────────────────────────────────────────────────────────────────────

@v1.get("/ping")
def ping():
    return jsonify({"ok": True})


# ── answer checking ───────────────────────────────────────────────────────────

@v1.post("/check")
@require_auth
def check():
    body = request.get_json(silent=True) or {}
    question = body.get("question", "")
    answer   = body.get("answer", "")
    context  = body.get("context", "")
    if not question or not answer:
        return jsonify({"error": "question and answer are required"}), 400
    result = core.check.run(question, answer, context, **_llm_kwargs())
    return jsonify(result)


# ── tutor session ─────────────────────────────────────────────────────────────

@v1.post("/tutor/start")
@require_auth
def tutor_start():
    body          = request.get_json(silent=True) or {}
    topic         = body.get("topic", "")
    context       = body.get("context", "")
    question_bank = body.get("question_bank", "")
    if not topic:
        return jsonify({"error": "topic is required"}), 400
    result = core.tutor.start(topic, context, question_bank, **_llm_kwargs())
    return jsonify(result)


@v1.post("/tutor/reply")
@require_auth
def tutor_reply():
    body            = request.get_json(silent=True) or {}
    messages        = body.get("messages")
    student_message = body.get("message", "")
    wrong_streak    = int(body.get("wrong_streak", 0))
    if not messages or not student_message:
        return jsonify({"error": "messages and message are required"}), 400
    result = core.tutor.reply(messages, student_message, wrong_streak, **_llm_kwargs())
    return jsonify(result)


# ── question extraction ───────────────────────────────────────────────────────

@v1.post("/questions/extract")
@require_auth
def questions_extract():
    if "file" not in request.files:
        return jsonify({"error": "multipart field 'file' (PDF) is required"}), 400
    pdf_bytes = request.files["file"].read()
    try:
        questions = core.questions.extract_from_paper(pdf_bytes, **_form_llm_kwargs())
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    return jsonify({"questions": questions, "count": len(questions)})


# ── handwritten step checker ─────────────────────────────────────────────────

@v1.post("/check/working")
@require_auth
def check_working():
    """Upload an image of handwritten working; get back per-step transcription
    and the index + explanation of the first wrong step, if any.

    Multipart fields:
      file         — image (JPEG / PNG recommended)
      model        — LLM model name (optional)
      provider     — ollama | groq (optional)
      api_key      — provider key (optional)
      host         — Ollama host (optional)
      vision_model — override the vision model (optional)
    """
    if "file" not in request.files:
        return jsonify({"error": "multipart field 'file' (image) is required"}), 400

    img_file = request.files["file"]
    suffix = os.path.splitext(img_file.filename or ".jpg")[1] or ".jpg"
    llm = _form_llm_kwargs(extra_keys=("vision_model",))

    # check_working() needs a file path; write to a temp file
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
        img_file.save(tmp)

    try:
        result = core.vision.step_checker.check_working(
            tmp_path,
            provider=llm.get("provider", "ollama"),
            model=llm.get("model", "gemma4"),
            host=llm.get("host", "http://localhost:11434"),
            api_key=llm.get("api_key", ""),
            vision_model=llm.get("vision_model", ""),
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 422
    finally:
        os.unlink(tmp_path)

    # boxes are tuples; convert to lists for JSON
    result["boxes"] = [list(b) for b in result.get("boxes", [])]
    return jsonify(result)

@v1.get("/curricula")
@require_auth
def curricula_list():
    out = []
    for cid in curricula.list_curricula():
        try:
            m = curricula.load(cid)
            out.append({"id": cid, "name": m.get("name", cid),
                        "subjects": m.get("subjects", [])})
        except Exception:
            out.append({"id": cid, "name": cid})
    return jsonify({"curricula": out})
@v1.get("/curricula/<cid>/topics")
@require_auth
def curricula_topics(cid: str):
    path = curricula.CURRICULA_DIR / cid / "topics.json"
    topics = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    return jsonify({"curriculum": cid, "topics": topics})

@v1.post("/progress")
@require_auth
def progress_record():
    body       = request.get_json(silent=True) or {}
    curriculum = (body.get("curriculum") or "").strip()
    topic      = (body.get("topic") or "").strip()
    if not curriculum or not topic:
        return jsonify({"error": "curriculum and topic are required"}), 400
    correct = bool(body.get("correct", False))
    users.record_progress(request.api_user["id"], curriculum, topic, correct)
    return jsonify({"ok": True})


@v1.get("/progress/<cid>")
@require_auth
def progress_read(cid: str):
    rows = users.get_progress(request.api_user["id"], cid)
    return jsonify({"curriculum": cid, "progress": rows})
# ── API key management (self-service) ─────────────────────────────────────────

@v1.get("/keys")
@require_auth
def keys_list():
    keys = users.list_api_keys(request.api_user["id"])
    return jsonify({"keys": keys})


@v1.post("/keys")
@require_auth
def keys_create():
    body  = request.get_json(silent=True) or {}
    label = (body.get("label") or "").strip()
    if not label:
        return jsonify({"error": "label is required"}), 400
    token = users.create_api_key(request.api_user["id"], label)
    return jsonify({"token": token, "note": "Save this — it will not be shown again."})


@v1.delete("/keys/<int:key_id>")
@require_auth
def keys_revoke(key_id: int):
    users.revoke_api_key(key_id, request.api_user["id"])
    return jsonify({"ok": True})
