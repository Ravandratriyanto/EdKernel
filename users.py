"""Accounts and login sessions — the prerequisite for a real `user_id`.

Phase B logs every turn with `user_id=None`, and the chat sidebar shows every
session on the server to anyone who opens the page. This is what makes that
column mean something.

Passwords are stored as scrypt hashes. Session tokens are stored only as a
hash of the token, so a leaked database yields no working cookies.
"""

import hashlib
import secrets
import sqlite3
import time
from pathlib import Path


DB_PATH = Path(__file__).parent / ".logs" / "users.db"



_N, _R, _P, _DKLEN, _SALT_BYTES = 2 ** 14, 8, 1, 32, 16

SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
MIN_PASSWORD_LENGTH = 8

VALID_ROLES = ("admin", "teacher", "student")


def _connect():
    """A fresh connection — SQLite connections can't cross threads, and Flask
    serves requests on threads."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    """Create both tables if they aren't there. Safe to call on every boot."""
    conn = _connect()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    created_at    INTEGER NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'student'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id    INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_expires "
                "ON sessions (expires_at)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id   INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                    key_hash   TEXT NOT NULL UNIQUE,
                    label      TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS progress (
                    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                    curriculum TEXT NOT NULL,
                    topic_id   TEXT NOT NULL,
                    attempts   INTEGER NOT NULL DEFAULT 0,
                    correct    INTEGER NOT NULL DEFAULT 0,
                    last_seen  INTEGER NOT NULL,
                    PRIMARY KEY (user_id, curriculum, topic_id)
                )
            """)
            # Migration: add role column to existing databases
            try:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student'"
                )
                # Promote the first account to admin on migration
                conn.execute(
                    "UPDATE users SET role = 'admin' WHERE id = (SELECT MIN(id) FROM users)"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
    finally:
        conn.close()


def _hash_password(password: str) -> str:
    """Hash a password with a fresh random salt. Parameters and salt go into
    the string itself — the verifier needs them to recompute."""
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN
    )
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """True if `password` produced `stored`. Never raises on a malformed row."""
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p),
            dklen=len(hash_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(dk.hex(), hash_hex)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class UserError(Exception):
    """Something the student did wrong: name taken, password too short."""


def create_user(username: str, password: str, role: str = "student") -> int:
    """Register an account. Returns the new user id.

    If this is the very first account in the database, it becomes admin
    regardless of the role argument — every deployment needs at least one.
    """
    username = (username or "").strip()
    if not username:
        raise UserError("Pick a username.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise UserError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if role not in VALID_ROLES:
        raise UserError(f"Invalid role '{role}'.")

    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            role = "admin"
        with conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, created_at, role) "
                "VALUES (?, ?, ?, ?)",
                (username, _hash_password(password), int(time.time()), role),
            )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise UserError("That username is taken.")
    finally:
        conn.close()


def authenticate(username: str, password: str) -> int | None:
    """Check a login. Returns the user id, or None if it doesn't match."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE username = ?",
            ((username or "").strip(),),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        _hash_password(password or "")
        return None
    if not _verify_password(password or "", row["password_hash"]):
        return None
    return row["id"]


def create_session(user_id: int) -> str:
    """Start a login session. Returns the token to hand the browser — the only
    time the plain token exists."""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (_hash_token(token), user_id, now, now + SESSION_TTL_SECONDS),
            )
    finally:
        conn.close()
    return token


def user_for_token(token: str) -> dict | None:
    """The logged-in user behind a token, or None if unknown or expired."""
    if not token:
        return None
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT u.id, u.username, u.role, s.expires_at "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ?",
            (_hash_token(token),),
        ).fetchone()
    finally:
        conn.close()

    if row is None or row["expires_at"] <= int(time.time()):
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def delete_session(token: str) -> None:
    """Log out. Deleting an already-gone token is not an error."""
    if not token:
        return
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),)
            )
    finally:
        conn.close()


def purge_expired() -> int:
    """Drop timed-out sessions. Returns how many went."""
    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),)
            )
        return cur.rowcount
    finally:
        conn.close()


def set_role(user_id: int, role: str) -> None:
    """Change a user's role. Raises UserError on bad role or unknown id."""
    if role not in VALID_ROLES:
        raise UserError(f"Invalid role '{role}'.")
    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE users SET role = ? WHERE id = ?", (role, user_id)
            )
        if cur.rowcount == 0:
            raise UserError("User not found.")
    finally:
        conn.close()


def list_users() -> list[dict]:
    """All accounts, newest first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, username, role, created_at FROM users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "username": r["username"],
             "role": r["role"], "created_at": r["created_at"]} for r in rows]


def create_api_key(owner_id: int, label: str) -> str:
    """Mint a new API key. Returns the plaintext token — the only time it exists."""
    token = secrets.token_urlsafe(32)
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO api_keys (owner_id, key_hash, label, created_at) "
                "VALUES (?, ?, ?, ?)",
                (owner_id, _hash_token(token), label.strip(), int(time.time())),
            )
    finally:
        conn.close()
    return token


def list_api_keys(owner_id: int) -> list[dict]:
    """All API keys for an owner — label and date only, never the hash."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, label, created_at FROM api_keys WHERE owner_id = ? ORDER BY id",
            (owner_id,),
        ).fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "label": r["label"], "created_at": r["created_at"]}
            for r in rows]


def revoke_api_key(key_id: int, owner_id: int) -> None:
    """Delete one API key. owner_id prevents admins revoking each other's keys accidentally."""
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "DELETE FROM api_keys WHERE id = ? AND owner_id = ?",
                (key_id, owner_id),
            )
    finally:
        conn.close()


def user_for_api_key(token: str) -> dict | None:
    """The user behind a Bearer token, or None if unknown."""
    if not token:
        return None
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT u.id, u.username, u.role "
            "FROM api_keys k JOIN users u ON u.id = k.owner_id "
            "WHERE k.key_hash = ?",
            (_hash_token(token),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def record_progress(user_id: int, curriculum: str, topic_id: str, correct: bool) -> None:
    """Upsert one answered question into the progress table."""
    now = int(time.time())
    inc = 1 if correct else 0
    conn = _connect()
    try:
        with conn:
            conn.execute("""
                INSERT INTO progress (user_id, curriculum, topic_id, attempts, correct, last_seen)
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(user_id, curriculum, topic_id) DO UPDATE SET
                    attempts  = attempts + 1,
                    correct   = correct  + ?,
                    last_seen = ?
            """, (user_id, curriculum, topic_id, inc, now, inc, now))
    finally:
        conn.close()


def get_progress(user_id: int, curriculum: str) -> list[dict]:
    """All topic rows for one student in one curriculum."""
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT topic_id, attempts, correct, last_seen
            FROM progress
            WHERE user_id = ? AND curriculum = ?
            ORDER BY last_seen DESC
        """, (user_id, curriculum)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_all_progress(curriculum: str) -> list[dict]:
    """All students' progress for a curriculum — for the teacher view."""
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT u.username, p.topic_id, p.attempts, p.correct, p.last_seen
            FROM progress p
            JOIN users u ON u.id = p.user_id
            WHERE p.curriculum = ?
            ORDER BY u.username, p.last_seen DESC
        """, (curriculum,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
