import hashlib
import json
import secrets
import sqlite3
import time
import os
from pathlib import Path
import gamify
_N, _R, _P, _DKLEN, _SALT_BYTES = (2 ** 14, 8, 1, 32, 16)
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
MIN_PASSWORD_LENGTH = 8
_DB_DIR = Path(os.getenv('DB_DIR', str(Path(__file__).parent / '.logs')))
DB_PATH = _DB_DIR / 'users.db'
VALID_ROLES = ('admin', 'teacher', 'student')

def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def init() -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute("\n                CREATE TABLE IF NOT EXISTS users (\n                    id            INTEGER PRIMARY KEY AUTOINCREMENT,\n                    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,\n                    password_hash TEXT NOT NULL,\n                    created_at    INTEGER NOT NULL,\n                    role          TEXT NOT NULL DEFAULT 'student'\n                )\n            ")
            conn.execute('\n                CREATE TABLE IF NOT EXISTS sessions (\n                    token_hash TEXT PRIMARY KEY,\n                    user_id    INTEGER NOT NULL,\n                    created_at INTEGER NOT NULL,\n                    expires_at INTEGER NOT NULL,\n                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE\n                )\n            ')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions (expires_at)')
            conn.execute('\n                CREATE TABLE IF NOT EXISTS api_keys (\n                    id         INTEGER PRIMARY KEY AUTOINCREMENT,\n                    owner_id   INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,\n                    key_hash   TEXT NOT NULL UNIQUE,\n                    label      TEXT NOT NULL,\n                    created_at INTEGER NOT NULL\n                )\n            ')
            conn.execute('\n                CREATE TABLE IF NOT EXISTS progress (\n                    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,\n                    curriculum TEXT NOT NULL,\n                    topic_id   TEXT NOT NULL,\n                    attempts   INTEGER NOT NULL DEFAULT 0,\n                    correct    INTEGER NOT NULL DEFAULT 0,\n                    last_seen  INTEGER NOT NULL,\n                    PRIMARY KEY (user_id, curriculum, topic_id)\n                )\n            ')
            conn.execute("\n                CREATE TABLE IF NOT EXISTS quiz_attempts (\n                    id           TEXT PRIMARY KEY,\n                    user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,\n                    curriculum   TEXT NOT NULL,\n                    topic        TEXT NOT NULL,\n                    questions    TEXT NOT NULL,\n                    answers      TEXT NOT NULL DEFAULT '{}',\n                    marked       TEXT NOT NULL DEFAULT '{}',\n                    started_at   INTEGER NOT NULL,\n                    submitted_at INTEGER,\n                    score        INTEGER,\n                    total        INTEGER NOT NULL,\n                    tab_switches INTEGER NOT NULL DEFAULT 0\n                )\n            ")
            conn.execute('CREATE INDEX IF NOT EXISTS idx_attempts_user ON quiz_attempts (user_id, started_at)')
            conn.execute('\n                CREATE TABLE IF NOT EXISTS misconceptions (\n                    id INTEGER PRIMARY KEY AUTOINCREMENT,\n                    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,\n                    curriculum TEXT NOT NULL,\n                    topic TEXT NOT NULL,\n                    category TEXT NOT NULL,\n                    ts INTEGER NOT NULL\n                )\n            ')
            conn.execute('\n                CREATE TABLE IF NOT EXISTS gamify (\n                    user_id        INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,\n                    xp             INTEGER NOT NULL DEFAULT 0,\n                    current_streak INTEGER NOT NULL DEFAULT 0,\n                    longest_streak INTEGER NOT NULL DEFAULT 0,\n                    last_active    TEXT\n                )\n            ')
            conn.execute('\n                CREATE TABLE IF NOT EXISTS daily_missions (\n                    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,\n                    date       TEXT NOT NULL,\n                    mission_id TEXT NOT NULL,\n                    count      INTEGER NOT NULL DEFAULT 0,\n                    PRIMARY KEY (user_id, date, mission_id)\n                )\n            ')
            conn.execute('\n                CREATE TABLE IF NOT EXISTS quests (\n                    user_id  INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,\n                    quest_id TEXT NOT NULL,\n                    progress INTEGER NOT NULL DEFAULT 0,\n                    done     INTEGER NOT NULL DEFAULT 0,\n                    PRIMARY KEY (user_id, quest_id)\n                )\n            ')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_misconceptions_curric ON misconceptions (curriculum, topic, category)')
            try:
                conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student'")
                conn.execute("UPDATE users SET role = 'admin' WHERE id = (SELECT MIN(id) FROM users)")
            except sqlite3.OperationalError:
                pass
    finally:
        conn.close()

def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f'scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}'

def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split('$')
        if scheme != 'scrypt':
            return False
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=len(hash_hex) // 2)
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(dk.hex(), hash_hex)

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

class UserError(Exception):
    pass

def create_user(username: str, password: str, role: str='student') -> int:
    username = (username or '').strip()
    if not username:
        raise UserError('Pick a username.')
    if len(password or '') < MIN_PASSWORD_LENGTH:
        raise UserError(f'Password must be at least {MIN_PASSWORD_LENGTH} characters.')
    if role not in VALID_ROLES:
        raise UserError(f"Invalid role '{role}'.")
    conn = _connect()
    try:
        count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        if count == 0:
            role = 'admin'
        with conn:
            cur = conn.execute('INSERT INTO users (username, password_hash, created_at, role) VALUES (?, ?, ?, ?)', (username, _hash_password(password), int(time.time()), role))
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise UserError('That username is taken.')
    finally:
        conn.close()

def authenticate(username: str, password: str) -> int | None:
    conn = _connect()
    try:
        row = conn.execute('SELECT id, password_hash FROM users WHERE username = ?', ((username or '').strip(),)).fetchone()
    finally:
        conn.close()
    if row is None:
        _hash_password(password or '')
        return None
    if not _verify_password(password or '', row['password_hash']):
        return None
    return row['id']

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    conn = _connect()
    try:
        with conn:
            conn.execute('INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)', (_hash_token(token), user_id, now, now + SESSION_TTL_SECONDS))
    finally:
        conn.close()
    return token

def user_for_token(token: str) -> dict | None:
    if not token:
        return None
    conn = _connect()
    try:
        row = conn.execute('SELECT u.id, u.username, u.role, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?', (_hash_token(token),)).fetchone()
    finally:
        conn.close()
    if row is None or row['expires_at'] <= int(time.time()):
        return None
    return {'id': row['id'], 'username': row['username'], 'role': row['role']}

def delete_session(token: str) -> None:
    if not token:
        return
    conn = _connect()
    try:
        with conn:
            conn.execute('DELETE FROM sessions WHERE token_hash = ?', (_hash_token(token),))
    finally:
        conn.close()

def purge_expired() -> int:
    conn = _connect()
    try:
        with conn:
            cur = conn.execute('DELETE FROM sessions WHERE expires_at <= ?', (int(time.time()),))
        return cur.rowcount
    finally:
        conn.close()

def set_role(user_id: int, role: str) -> None:
    if role not in VALID_ROLES:
        raise UserError(f"Invalid role '{role}'.")
    conn = _connect()
    try:
        with conn:
            cur = conn.execute('UPDATE users SET role = ? WHERE id = ?', (role, user_id))
        if cur.rowcount == 0:
            raise UserError('User not found.')
    finally:
        conn.close()

def list_users() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute('SELECT id, username, role, created_at FROM users ORDER BY id').fetchall()
    finally:
        conn.close()
    return [{'id': r['id'], 'username': r['username'], 'role': r['role'], 'created_at': r['created_at']} for r in rows]

def create_api_key(owner_id: int, label: str) -> str:
    token = secrets.token_urlsafe(32)
    conn = _connect()
    try:
        with conn:
            conn.execute('INSERT INTO api_keys (owner_id, key_hash, label, created_at) VALUES (?, ?, ?, ?)', (owner_id, _hash_token(token), label.strip(), int(time.time())))
    finally:
        conn.close()
    return token

def list_api_keys(owner_id: int) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute('SELECT id, label, created_at FROM api_keys WHERE owner_id = ? ORDER BY id', (owner_id,)).fetchall()
    finally:
        conn.close()
    return [{'id': r['id'], 'label': r['label'], 'created_at': r['created_at']} for r in rows]

def revoke_api_key(key_id: int, owner_id: int) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute('DELETE FROM api_keys WHERE id = ? AND owner_id = ?', (key_id, owner_id))
    finally:
        conn.close()

def user_for_api_key(token: str) -> dict | None:
    if not token:
        return None
    conn = _connect()
    try:
        row = conn.execute('SELECT u.id, u.username, u.role FROM api_keys k JOIN users u ON u.id = k.owner_id WHERE k.key_hash = ?', (_hash_token(token),)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {'id': row['id'], 'username': row['username'], 'role': row['role']}

def record_progress(user_id: int, curriculum: str, topic_id: str, correct: bool) -> None:
    now = int(time.time())
    inc = 1 if correct else 0
    conn = _connect()
    try:
        with conn:
            conn.execute('\n                INSERT INTO progress (user_id, curriculum, topic_id, attempts, correct, last_seen)\n                VALUES (?, ?, ?, 1, ?, ?)\n                ON CONFLICT(user_id, curriculum, topic_id) DO UPDATE SET\n                    attempts  = attempts + 1,\n                    correct   = correct  + ?,\n                    last_seen = ?\n            ', (user_id, curriculum, topic_id, inc, now, inc, now))
    finally:
        conn.close()

def record_activity(user_id: int, event: str, correct: bool | None=None) -> None:
    today = time.strftime('%Y-%m-%d')
    yesterday = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))
    conn = _connect()
    try:
        with conn:
            row = conn.execute('SELECT xp, current_streak, longest_streak, last_active FROM gamify WHERE user_id=?', (user_id,)).fetchone()
            xp, cur, longest, last = (row['xp'], row['current_streak'], row['longest_streak'], row['last_active']) if row else (0, 0, 0, None)
            if last != today:
                cur = cur + 1 if last == yesterday else 1
                longest = max(longest, cur)
            xp += gamify.XP['answer_correct'] if event == 'answer' and correct else gamify.XP['answer'] if event == 'answer' else gamify.XP.get(event, 0)
            for mid, (label, mevent, target) in gamify.MISSIONS.items():
                if mevent != event:
                    continue
                cnt_row = conn.execute('SELECT count FROM daily_missions WHERE user_id=? AND date=? AND mission_id=?', (user_id, today, mid)).fetchone()
                cnt = cnt_row['count'] if cnt_row else 0
                if cnt >= target:
                    continue
                cnt += 1
                conn.execute('INSERT INTO daily_missions (user_id, date, mission_id, count) VALUES (?,?,?,?) ON CONFLICT(user_id, date, mission_id) DO UPDATE SET count=?', (user_id, today, mid, cnt, cnt))
                if cnt == target:
                    xp += gamify.XP['mission_complete']
            conn.execute('INSERT INTO gamify (user_id, xp, current_streak, longest_streak, last_active) VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET xp=?, current_streak=?, longest_streak=?, last_active=?', (user_id, xp, cur, longest, today, xp, cur, longest, today))
            mastered = conn.execute('SELECT COUNT(*) AS n FROM progress WHERE user_id=? AND attempts>0 AND CAST(correct AS FLOAT)/attempts >= 0.8', (user_id,)).fetchone()['n']
            for qid, (label, kind, target) in gamify.QUESTS.items():
                prog = {'streak': cur, 'xp': xp, 'mastery': mastered}[kind]
                p = min(prog, target)
                conn.execute('INSERT INTO quests (user_id, quest_id, progress, done) VALUES (?,?,?,?) ON CONFLICT(user_id, quest_id) DO UPDATE SET progress=?, done=?', (user_id, qid, p, int(prog >= target), p, int(prog >= target)))
    finally:
        conn.close()

def get_gamify(user_id: int) -> dict:
    today = time.strftime('%Y-%m-%d')
    conn = _connect()
    try:
        row = conn.execute('SELECT xp, current_streak, longest_streak FROM gamify WHERE user_id=?', (user_id,)).fetchone()
        xp = row['xp'] if row else 0
        streak = row['current_streak'] if row else 0
        longest = row['longest_streak'] if row else 0
        counts = {r['mission_id']: r['count'] for r in conn.execute('SELECT mission_id, count FROM daily_missions WHERE user_id=? AND date=?', (user_id, today)).fetchall()}
        missions = [{'id': mid, 'label': label, 'count': min(counts.get(mid, 0), target), 'target': target, 'done': counts.get(mid, 0) >= target} for mid, (label, _ev, target) in gamify.MISSIONS.items()]
        qrows = {r['quest_id']: r for r in conn.execute('SELECT quest_id, progress, done FROM quests WHERE user_id=?', (user_id,)).fetchall()}
        quests = [{'id': qid, 'label': label, 'target': target, 'progress': qrows[qid]['progress'] if qid in qrows else 0, 'done': bool(qrows[qid]['done']) if qid in qrows else False} for qid, (label, _k, target) in gamify.QUESTS.items()]
    finally:
        conn.close()
    return {'xp': xp, 'level': gamify.level_for_xp(xp), 'streak': streak, 'longest': longest, 'missions': missions, 'quests': quests}

def create_attempt(user_id: int, curriculum: str, topic: str, questions: list[dict]) -> str:
    attempt_id = secrets.token_hex(16)
    conn = _connect()
    try:
        with conn:
            conn.execute('INSERT INTO quiz_attempts (id, user_id, curriculum, topic, questions, started_at, total) VALUES (?, ?, ?, ?, ?, ?, ?)', (attempt_id, user_id, curriculum, topic, json.dumps(questions), int(time.time()), len(questions)))
    finally:
        conn.close()
    return attempt_id

def get_attempt(attempt_id: str, user_id: int) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute('SELECT * FROM quiz_attempts WHERE id = ? AND user_id = ?', (attempt_id, user_id)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    out = dict(row)
    out['questions'] = json.loads(out['questions'])
    out['answers'] = json.loads(out['answers'])
    out['marked'] = json.loads(out['marked'])
    return out

def record_answer(attempt_id: str, user_id: int, qid: str, choice: str, correct: bool) -> None:
    conn = _connect()
    try:
        with conn:
            row = conn.execute('SELECT answers, marked FROM quiz_attempts WHERE id = ? AND user_id = ?', (attempt_id, user_id)).fetchone()
            if row is None:
                return
            answers = json.loads(row['answers'])
            marked = json.loads(row['marked'])
            answers[qid] = choice
            marked[qid] = bool(correct)
            conn.execute('UPDATE quiz_attempts SET answers = ?, marked = ? WHERE id = ? AND user_id = ?', (json.dumps(answers), json.dumps(marked), attempt_id, user_id))
    finally:
        conn.close()

def already_marked(attempt_id: str, user_id: int, qid: str) -> bool:
    attempt = get_attempt(attempt_id, user_id)
    return bool(attempt and qid in attempt['marked'])

def bump_tab_switch(attempt_id: str, user_id: int) -> int:
    conn = _connect()
    try:
        with conn:
            conn.execute('UPDATE quiz_attempts SET tab_switches = tab_switches + 1 WHERE id = ? AND user_id = ?', (attempt_id, user_id))
            row = conn.execute('SELECT tab_switches FROM quiz_attempts WHERE id = ? AND user_id = ?', (attempt_id, user_id)).fetchone()
    finally:
        conn.close()
    return row['tab_switches'] if row else 0

def finish_attempt(attempt_id: str, user_id: int, score: int) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute('UPDATE quiz_attempts SET submitted_at = ?, score = ? WHERE id = ? AND user_id = ? AND submitted_at IS NULL', (int(time.time()), score, attempt_id, user_id))
    finally:
        conn.close()

def list_attempts(curriculum: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute('\n            SELECT a.id, u.username, a.topic, a.score, a.total,\n                   a.tab_switches, a.started_at, a.submitted_at\n            FROM quiz_attempts a\n            JOIN users u ON u.id = a.user_id\n            WHERE a.curriculum = ? AND a.submitted_at IS NOT NULL\n            ORDER BY a.submitted_at DESC\n        ', (curriculum,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

def study_deltas() -> list[dict]:
    conn = _connect()
    try: 
        rows = conn.execute('''
        SELECT u.username, a.user_id, a.curriculum, a.topic, a.score, a.total, a.submitted_at 
        FROM quiz_attempts a JOIN users u ON u.id = a.user_id
        WHERE a.submitted_at IS NOT NULL
        ORDER BY a.submitted_at ASC
        ''').fetchall()
    finally:
        conn.close()
    groups = {}
    for r in rows:
        groups.setdefault((r['user_id'], r['curriculum'], r['topic']), []).append(r)
    out = []
    for (uid, cur, topic), atts in groups.items():
        first, last = atts[0], atts[-1]
        out.append({'username': first['username'], 'topic': topic,'attempts': len(atts),'pre_score': first['score'], 'pre_total': first['total'],'post_score': last['score'], 'post_total': last['total']})
    return out
def get_progress(user_id: int, curriculum: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute('\n            SELECT topic_id, attempts, correct, last_seen\n            FROM progress\n            WHERE user_id = ? AND curriculum = ?\n            ORDER BY last_seen DESC\n        ', (user_id, curriculum)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

def get_all_progress(curriculum: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute('\n            SELECT u.username, p.topic_id, p.attempts, p.correct, p.last_seen\n            FROM progress p\n            JOIN users u ON u.id = p.user_id\n            WHERE p.curriculum = ?\n            ORDER BY u.username, p.last_seen DESC\n        ', (curriculum,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]

def record_misconception(user_id: int, curriculum: str, topic: str, category: str) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute('INSERT INTO misconceptions (user_id, curriculum, topic, category, ts) VALUES (?, ?, ?, ?, ?)', (user_id, curriculum, topic, category, int(time.time())))
    finally:
        conn.close()

def get_misconceptions(curriculum: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute('\n            SELECT topic, category,\n                   COUNT(DISTINCT user_id) AS students,\n                   COUNT(*)                AS occurrences,\n                   MAX(ts)                 AS last_seen\n            FROM misconceptions\n            WHERE curriculum = ?\n            GROUP BY topic, category\n            ORDER BY students DESC, occurrences DESC\n        ', (curriculum,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]