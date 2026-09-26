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
def all_sessions(limit: int = 200) -> list[dict]:
    sessions = {}
    for rec in read_records():
        sid = rec.get('session_id') or ''
        if not sid:
            continue 
        s = sessions.get(sid)
        if s is None:
            s = sessions[sid] = {'session_id': sid, 'user_id': rec.get('userid'), 'mode': rec.get('mode', 'learn'), 'title': '', 'turns': 0, 'started': rec.get('ts', ''), 'updated': rec.get('ts', '') }
            s['turns'] += 1
        s['updated'] = rec.get('ts', s['updated'])
        if not s['title']:
            s['title'] = (rec.get('topic') or rec.get('input') or '').strip()[:80]
    return sorted(sessions.values(), key=lambda s: s['updated'], reverse=True)[:limit]

def session_turns_admin(session_id: str) -> list[dict]:
    return [r for r in read_records() if r.get('session_id') == session_id]
def stats() -> dict:
    recs = read_records()
    by_event, users, sessions = {}, set(), set()
    correct = wrong = lat_sum = lat_n = tokens = 0
    for r in recs:
        by_event[r.get('event', '?')] = by_event.get(r.get('event', '?'), 0) + 1
        if r.get('user_id') is not None:
            users.add(r['user_id'])
        if r.get('session_id'):
            sessions.add(r['session_id'])
        if r.get('correct') is True:
            correct += 1
        elif r.get('correct') is False:
            wrong += 1
        lm = r.get('latency_ms')
        if isinstance(lm, (int, float)):
            lat_sum += lm
            lat_n += 1
        tk = r.get('tokens') or {}
        if isinstance(tk, dict):
            tokens += tk.get('total_tokens') or tk.get('total') or 0
    return {'turns': len(recs), 'users': len(users), 'sessions': len(sessions), 'by_event': by_event, 'correct': correct, 'wrong': wrong,'avg_latency_ms': round(lat_sum / lat_n) if lat_n else 0,'total_tokens': tokens, 'last_ts': recs[-1].get('ts') if recs else None}
