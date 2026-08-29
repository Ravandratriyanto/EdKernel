"""Stateless REST API — /v1/

Auth: Authorization: Bearer <token>
Every route returns JSON. No cookies, no sessions, no HTML.
"""

import functools
import os
import tempfile
from flask import Blueprint, request, jsonify

import users
import core.check
import core.tutor
import core.questions
import core.vision.step_checker

v1 = Blueprint("v1", __name__, url_prefix="/v1")


def _llm_kwargs() -> dict:
    """Pull model/provider/api_key/host from request JSON if provided."""
    body = request.get_json(silent=True) or {}
    out = {}
    for key in ("model", "provider", "api_key", "host"):
        if key in body:
            out[key] = body[key]
    return out


def _bearer_user():
    """Resolve the Bearer token to a user dict, or return None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return users.user_for_api_key(auth[7:])


def require_auth(f):
    """Decorator: 401 if no valid Bearer token."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = _bearer_user()
        if user is None:
            return jsonify({"error": "Invalid or missing API key"}), 401
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
    # llm kwargs come from form fields, not JSON body
    llm = {}
    for key in ("model", "provider", "api_key", "host"):
        val = request.form.get(key)
        if val:
            llm[key] = val
    try:
        questions = core.questions.extract_from_paper(pdf_bytes, **llm)
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    return jsonify({"questions": questions, "count": len(questions)})


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
