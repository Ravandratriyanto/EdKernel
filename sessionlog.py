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
