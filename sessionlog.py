"""Append-only session log — Phase B.

One JSON line per tutor turn, written to .logs/sessions.jsonl. This is the
input to Phase C fine-tuning and the raw material for per-student metering, so
the fields have to be enough to rebuild a conversation in order.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).parent / ".logs"
LOG_PATH = LOG_DIR / "sessions.jsonl"

# Flask serves requests on threads, so two turns can finish at once. A record
# here is bigger than the 4KB a kernel appends atomically, so take a lock.
_lock = threading.Lock()


def log_turn(event: str, **fields) -> None:
    """Append one line to the session log. Never raises."""
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
            **fields,
        }
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        # default=str so an unexpected object stringifies instead of throwing.
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _lock, LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # A logging failure must never cost the student their lesson.
        pass


def attachment_meta(attachment: dict | None) -> dict | None:
    """Type, name and size only — never the bytes.

    A base64 image is hundreds of KB and the most sensitive thing in the
    request. The log records shapes and counts, not contents.
    """
    if not attachment:
        return None
    kind = attachment.get("type")
    meta = {"type": kind, "name": attachment.get("name", "")}
    if kind == "image":
        meta["b64_chars"] = len(attachment.get("b64") or "")
    elif kind == "pdf":
        meta["text_chars"] = len(attachment.get("text") or "")
    return meta


def read_records() -> list[dict]:
    """Every record in the log, oldest first. Unparseable lines are skipped.

    Takes the same lock as the writer so a half-written final line can't be
    read mid-append.
    """
    if not LOG_PATH.exists():
        return []
    records = []
    with _lock, LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue          # one bad line is not worth losing the history over
    return records


def list_sessions(user_id: int, limit: int = 50) -> list[dict]:
    """One summary per session id, newest first — this user's sessions only.

    user_id is positional and required on purpose. A new caller that forgets it
    fails immediately with a TypeError; a default would have quietly served
    every student's lessons to whoever asked.
    """
    sessions = {}
    for rec in read_records():
        sid = rec.get("session_id") or ""
        if not sid:
            continue              # pre-sidebar rows — nothing to open them by
        if rec.get("user_id") != user_id:
            continue              # someone else's lesson, or a pre-auth row
        s = sessions.get(sid)
        if s is None:
            s = sessions[sid] = {
                "session_id": sid,
                "mode":    rec.get("mode", "learn"),
                "title":   "",
                "turns":   0,
                "started": rec.get("ts", ""),
                "updated": rec.get("ts", ""),
            }
        s["turns"] += 1
        s["updated"] = rec.get("ts", s["updated"])
        if not s["title"]:
            s["title"] = (rec.get("topic") or rec.get("input") or "").strip()
    # ISO-8601 timestamps sort correctly as plain strings, so no date parsing.
    return sorted(sessions.values(),
                  key=lambda s: s["updated"], reverse=True)[:limit]


def session_turns(session_id: str, user_id: int) -> list[dict]:
    """Every turn of one session, oldest first — empty unless it's this user's.

    Guessing a session id must not be enough to read the lesson, so the owner
    check happens here rather than in the route.
    """
    return [r for r in read_records()
            if r.get("session_id") == session_id and r.get("user_id") == user_id]
