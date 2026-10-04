#!/usr/bin/env python3
"""NoteShare: a small note-taking app with a JSON API and a web page.

Uses only the Python standard library, so there is nothing to install.
Data is stored in ./data/noteshare.db (SQLite).
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "noteshare.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

SESSION_DAYS = 30
MAX_REQUEST_BYTES = 1_000_000
MAX_EMAIL_LEN = 254
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 1024
MAX_TITLE_LEN = 200
MAX_BODY_LEN = 100_000

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Static files the server is allowed to send: url path -> (file, content type)
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass
    with db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at    INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title       TEXT NOT NULL,
                body        TEXT NOT NULL,
                share_token TEXT UNIQUE,
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS notes_user ON notes(user_id);
            CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
            """
        )
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))


# --------------------------------------------------------------------------
# Passwords and tokens
# --------------------------------------------------------------------------

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        _, n, r, p, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# Used so that logging in with an unknown email takes as long as a wrong password.
DUMMY_HASH = hash_password(secrets.token_hex(16))


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Simple in-memory limit on failed logins (slows down password guessing)
# --------------------------------------------------------------------------

LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES_PER_EMAIL = 10
LOGIN_MAX_FAILURES_PER_IP = 100
_login_failures = {}
_login_lock = threading.Lock()


def _recent_failures(key, now):
    times = [t for t in _login_failures.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    if times:
        _login_failures[key] = times
    else:
        _login_failures.pop(key, None)
    return times


def login_blocked(keys):
    now = time.time()
    with _login_lock:
        for k in keys:
            limit = LOGIN_MAX_FAILURES_PER_IP if k.startswith("ip:") else LOGIN_MAX_FAILURES_PER_EMAIL
            if len(_recent_failures(k, now)) >= limit:
                return True
        return False


def record_login_failure(keys):
    now = time.time()
    with _login_lock:
        for k in keys:
            _recent_failures(k, now)
            _login_failures.setdefault(k, []).append(now)


def clear_login_failures(keys):
    with _login_lock:
        for k in keys:
            _login_failures.pop(k, None)


# --------------------------------------------------------------------------
# HTTP handling
# --------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def note_json(row, owner=True):
    data = {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if owner:
        data["shared"] = row["share_token"] is not None
        data["share_token"] = row["share_token"]
    return data


def clean_text(value, field, max_len, required):
    if value is None:
        if required:
            raise ApiError(400, f"'{field}' is required")
        return None
    if not isinstance(value, str):
        raise ApiError(400, f"'{field}' must be a string")
    if len(value) > max_len:
        raise ApiError(400, f"'{field}' is too long (max {max_len} characters)")
    return value


NOTE_PATH = re.compile(r"^/api/notes/(\d{1,18})$")
SHARE_PATH = re.compile(r"^/api/notes/(\d{1,18})/share$")
SHARED_PATH = re.compile(r"^/api/shared/([A-Za-z0-9_-]{1,100})$")
SHARED_PAGE = re.compile(r"^/s/[A-Za-z0-9_-]{1,100}$")


class Handler(BaseHTTPRequestHandler):
    server_version = "NoteShare"
    sys_version = ""

    # ---- response helpers -------------------------------------------------

    def _common_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )

    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._common_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_empty(self, status=204):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self._common_headers()
        self.end_headers()

    def send_static(self, name, content_type):
        try:
            with open(os.path.join(STATIC_DIR, name), "rb") as f:
                body = f.read()
        except OSError:
            return self.send_json(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._common_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Log method and path only, never tokens in headers. Hide share tokens in paths.
        msg = fmt % args
        msg = re.sub(r"(/api/shared/|/s/)[A-Za-z0-9_-]+", r"\1<token>", msg)
        sys.stderr.write(f"{self.log_date_time_string()} {msg}\n")

    # ---- request helpers --------------------------------------------------

    def read_json(self):
        length_header = self.headers.get("Content-Length")
        if self.headers.get("Transfer-Encoding"):
            raise ApiError(411, "Content-Length is required")
        try:
            length = int(length_header or 0)
        except ValueError:
            raise ApiError(400, "bad Content-Length")
        if length < 0:
            raise ApiError(400, "bad Content-Length")
        if length > MAX_REQUEST_BYTES:
            raise ApiError(413, "request too large")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            raise ApiError(400, "request body must be JSON")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "request body must be a JSON object")
        return data

    def current_user(self, conn):
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token or len(token) > 200:
            raise ApiError(401, "login required")
        row = conn.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
            (token_hash(token),),
        ).fetchone()
        if row is None or row["expires_at"] < time.time():
            raise ApiError(401, "login required")
        return row["user_id"]

    def own_note(self, conn, user_id, note_id):
        row = conn.execute(
            "SELECT * FROM notes WHERE id = ? AND user_id = ?", (int(note_id), user_id)
        ).fetchone()
        if row is None:
            # Same answer whether the note doesn't exist or belongs to someone else.
            raise ApiError(404, "note not found")
        return row

    # ---- dispatch ---------------------------------------------------------

    def handle_request(self):
        path = urlsplit(self.path).path
        method = self.command
        try:
            if path.startswith("/api/"):
                conn = db()
                try:
                    with conn:  # commits on success, rolls back on error
                        self.route_api(conn, method, path)
                finally:
                    conn.close()
            elif method in ("GET", "HEAD") and path in STATIC_FILES:
                self.send_static(*STATIC_FILES[path])
            elif method in ("GET", "HEAD") and SHARED_PAGE.match(path):
                self.send_static(*STATIC_FILES["/"])
            else:
                raise ApiError(404, "not found")
        except ApiError as e:
            self.send_json(e.status, {"error": e.message})
        except Exception:
            import traceback
            traceback.print_exc()
            self.send_json(500, {"error": "internal server error"})

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = handle_request

    def route_api(self, conn, method, path):
        now = int(time.time())

        if path == "/api/signup":
            if method != "POST":
                raise ApiError(405, "method not allowed")
            return self.signup(conn, now)

        if path == "/api/login":
            if method != "POST":
                raise ApiError(405, "method not allowed")
            return self.login(conn, now)

        m = SHARED_PATH.match(path)
        if m:
            if method not in ("GET", "HEAD"):
                raise ApiError(405, "method not allowed")
            row = conn.execute(
                "SELECT * FROM notes WHERE share_token = ?", (m.group(1),)
            ).fetchone()
            if row is None:
                raise ApiError(404, "shared note not found")
            return self.send_json(200, note_json(row, owner=False))

        # Everything below needs a logged-in user.
        user_id = self.current_user(conn)

        if path == "/api/logout":
            if method != "POST":
                raise ApiError(405, "method not allowed")
            token = self.headers.get("Authorization", "").partition(" ")[2].strip()
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
            return self.send_json(200, {"ok": True})

        if path == "/api/me":
            if method not in ("GET", "HEAD"):
                raise ApiError(405, "method not allowed")
            row = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
            return self.send_json(200, {"email": row["email"]})

        if path in ("/api/notes", "/api/notes/"):
            if method in ("GET", "HEAD"):
                rows = conn.execute(
                    "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
                    (user_id,),
                ).fetchall()
                return self.send_json(200, [note_json(r) for r in rows])
            if method == "POST":
                data = self.read_json()
                title = clean_text(data.get("title"), "title", MAX_TITLE_LEN, True)
                body = clean_text(data.get("body", ""), "body", MAX_BODY_LEN, False) or ""
                if not title.strip():
                    raise ApiError(400, "'title' must not be empty")
                cur = conn.execute(
                    "INSERT INTO notes (user_id, title, body, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, title, body, now, now),
                )
                row = conn.execute("SELECT * FROM notes WHERE id = ?", (cur.lastrowid,)).fetchone()
                return self.send_json(201, note_json(row))
            raise ApiError(405, "method not allowed")

        m = NOTE_PATH.match(path)
        if m:
            note = self.own_note(conn, user_id, m.group(1))
            if method in ("GET", "HEAD"):
                return self.send_json(200, note_json(note))
            if method in ("PUT", "PATCH"):
                data = self.read_json()
                title = clean_text(data.get("title"), "title", MAX_TITLE_LEN, False)
                body = clean_text(data.get("body"), "body", MAX_BODY_LEN, False)
                if title is None and body is None:
                    raise ApiError(400, "send 'title' and/or 'body'")
                if title is not None and not title.strip():
                    raise ApiError(400, "'title' must not be empty")
                conn.execute(
                    "UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                    (title if title is not None else note["title"],
                     body if body is not None else note["body"],
                     now, note["id"], user_id),
                )
                row = conn.execute("SELECT * FROM notes WHERE id = ?", (note["id"],)).fetchone()
                return self.send_json(200, note_json(row))
            if method == "DELETE":
                conn.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note["id"], user_id))
                return self.send_json(200, {"ok": True})
            raise ApiError(405, "method not allowed")

        m = SHARE_PATH.match(path)
        if m:
            note = self.own_note(conn, user_id, m.group(1))
            if method == "POST":
                share_token = note["share_token"]
                if share_token is None:
                    share_token = secrets.token_urlsafe(24)
                    conn.execute(
                        "UPDATE notes SET share_token = ? WHERE id = ? AND user_id = ?",
                        (share_token, note["id"], user_id),
                    )
                return self.send_json(200, {"share_token": share_token,
                                            "share_url": f"/s/{share_token}"})
            if method == "DELETE":
                # Stop sharing: the old link stops working.
                conn.execute(
                    "UPDATE notes SET share_token = NULL WHERE id = ? AND user_id = ?",
                    (note["id"], user_id),
                )
                return self.send_json(200, {"ok": True})
            raise ApiError(405, "method not allowed")

        raise ApiError(404, "not found")

    # ---- accounts ---------------------------------------------------------

    def signup(self, conn, now):
        data = self.read_json()
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            raise ApiError(400, "'email' and 'password' are required")
        email = email.strip().lower()
        if len(email) > MAX_EMAIL_LEN or not EMAIL_RE.match(email):
            raise ApiError(400, "please enter a valid email address")
        if len(password) < MIN_PASSWORD_LEN:
            raise ApiError(400, f"password must be at least {MIN_PASSWORD_LEN} characters")
        if len(password) > MAX_PASSWORD_LEN:
            raise ApiError(400, "password is too long")
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, hash_password(password), now),
            )
        except sqlite3.IntegrityError:
            raise ApiError(409, "an account with that email already exists")
        return self.send_json(201, {"id": cur.lastrowid, "email": email})

    def login(self, conn, now):
        data = self.read_json()
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            raise ApiError(400, "'email' and 'password' are required")
        email = email.strip().lower()[:MAX_EMAIL_LEN]
        password = password[:MAX_PASSWORD_LEN + 1]
        keys = ["email:" + email, "ip:" + self.client_address[0]]
        if login_blocked(keys):
            raise ApiError(429, "too many failed logins, please wait a few minutes")
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
        ok = verify_password(password, row["password_hash"] if row else DUMMY_HASH)
        if not row or not ok:
            record_login_failure(keys)
            raise ApiError(401, "wrong email or password")
        clear_login_failures(["email:" + email])
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash(token), row["id"], now, now + SESSION_DAYS * 86400),
        )
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        return self.send_json(200, {"token": token})


def main():
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    init_db()
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"NoteShare running on http://localhost:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
