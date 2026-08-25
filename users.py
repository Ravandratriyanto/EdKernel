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
                    created_at    INTEGER NOT NULL
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


def create_user(username: str, password: str) -> int:
    """Register an account. Returns the new user id."""
    username = (username or "").strip()
    if not username:
        raise UserError("Pick a username.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise UserError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, created_at) "
                "VALUES (?, ?, ?)",
                (username, _hash_password(password), int(time.time())),
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
            "SELECT u.id AS id, u.username AS username, s.expires_at AS expires_at "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ?",
            (_hash_token(token),),
        ).fetchone()
    finally:
        conn.close()

    if row is None or row["expires_at"] <= int(time.time()):
        return None
    return {"id": row["id"], "username": row["username"]}


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
