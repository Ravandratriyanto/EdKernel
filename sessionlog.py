import json
import threading
from datetime import datetime, timezone
from pathlib import Path
LOG_DIR = Path(__file__).parent / '.logs'
LOG_PATH = LOG_DIR / 'sessions.jsonl'
_lock = threading.Lock()

def log_turn(event: str, **fields) -> None:
    try:
        record = {'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'event': event, **fields}
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _lock, LOG_PATH.open('a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

def attachment_meta(attachment: dict | None) -> dict | None:
    if not attachment:
        return None
    kind = attachment.get('type')
    meta = {'type': kind, 'name': attachment.get('name', '')}
    if kind == 'image':
        meta['b64_chars'] = len(attachment.get('b64') or '')
    elif kind == 'pdf':
        meta['text_chars'] = len(attachment.get('text') or '')
    return meta

def read_records() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    records = []
    with _lock, LOG_PATH.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records

def list_sessions(user_id: int, limit: int=50) -> list[dict]:
    sessions = {}
    for rec in read_records():
        sid = rec.get('session_id') or ''
        if not sid:
            continue
        if rec.get('user_id') != user_id:
            continue
        s = sessions.get(sid)
        if s is None:
            s = sessions[sid] = {'session_id': sid, 'mode': rec.get('mode', 'learn'), 'title': '', 'turns': 0, 'started': rec.get('ts', ''), 'updated': rec.get('ts', '')}
        s['turns'] += 1
        s['updated'] = rec.get('ts', s['updated'])
        if not s['title']:
            s['title'] = (rec.get('topic') or rec.get('input') or '').strip()
    return sorted(sessions.values(), key=lambda s: s['updated'], reverse=True)[:limit]

def session_turns(session_id: str, user_id: int) -> list[dict]:
    return [r for r in read_records() if r.get('session_id') == session_id and r.get('user_id') == user_id]