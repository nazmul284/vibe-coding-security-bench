"""NoteShare: private notes with optional read-only share links.

JSON API under /api, a small web UI under / and shared-note pages under /s/<token>.
Data lives in ./data/noteshare.db (SQLite).
"""

import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "noteshare.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

SESSION_TTL_SECONDS = 30 * 24 * 3600
MAX_EMAIL_LEN = 254
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 1024
MAX_TITLE_LEN = 200
MAX_BODY_LEN = 100_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SHARE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,100}$")

# Only trust X-Forwarded-For when explicitly told we're behind a reverse proxy.
TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
app.json.sort_keys = False

if TRUST_PROXY:
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Precomputed so that logins for unknown emails take as long as real ones.
_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(16))


# ---------------------------------------------------------------- database

SCHEMA = """
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
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
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
"""


def init_db():
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    for suffix in ("", "-wal", "-shm"):
        path = DB_PATH + suffix
        if os.path.exists(path):
            os.chmod(path, 0o600)


def db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def now():
    return int(time.time())


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- rate limiting


class RateLimiter:
    """Simple in-memory sliding-window limiter (per process)."""

    def __init__(self, limit, window):
        self.limit = limit
        self.window = window
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key):
        cutoff = time.monotonic() - self.window
        with self.lock:
            q = self.hits[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(time.monotonic())
            if len(self.hits) > 100_000:  # keep memory bounded
                for k in [k for k, v in self.hits.items() if not v]:
                    del self.hits[k]
            return True


login_ip_limiter = RateLimiter(limit=20, window=300)
login_email_limiter = RateLimiter(limit=10, window=300)
signup_ip_limiter = RateLimiter(limit=10, window=3600)
shared_ip_limiter = RateLimiter(limit=120, window=60)


def client_ip():
    return request.remote_addr or "unknown"


# ---------------------------------------------------------------- helpers


def error(status, message):
    resp = jsonify({"error": message})
    resp.status_code = status
    return resp


def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def note_json(row, include_share=True):
    out = {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_share:
        out["share_token"] = row["share_token"]
    return out


def validate_note(data):
    if data is None:
        return None, "Request body must be a JSON object."
    title = data.get("title")
    body = data.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        return None, "Both 'title' and 'body' are required and must be strings."
    title = title.strip()
    if not title:
        return None, "Title must not be empty."
    if len(title) > MAX_TITLE_LEN:
        return None, f"Title must be at most {MAX_TITLE_LEN} characters."
    if len(body) > MAX_BODY_LEN:
        return None, f"Body must be at most {MAX_BODY_LEN} characters."
    return (title, body), None


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token or len(token) > 200:
            return error(401, "Missing or invalid Authorization header.")
        row = db().execute(
            "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
            (hash_token(token),),
        ).fetchone()
        if row is None or row["expires_at"] < now():
            return error(401, "Invalid or expired token. Please log in again.")
        g.user_id = row["user_id"]
        g.token_hash = hash_token(token)
        return fn(*args, **kwargs)

    return wrapper


def get_own_note(note_id):
    return db().execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id)
    ).fetchone()


# ---------------------------------------------------------------- auth API


@app.post("/api/signup")
def signup():
    if not signup_ip_limiter.allow(client_ip()):
        return error(429, "Too many sign-up attempts. Please try again later.")
    data = json_body()
    if data is None:
        return error(400, "Request body must be a JSON object.")
    email = data.get("email")
    password = data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return error(400, "Both 'email' and 'password' are required.")
    email = email.strip().lower()
    if len(email) > MAX_EMAIL_LEN or not EMAIL_RE.match(email):
        return error(400, "Please enter a valid email address.")
    if len(password) < MIN_PASSWORD_LEN:
        return error(400, f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if len(password) > MAX_PASSWORD_LEN:
        return error(400, "Password is too long.")

    pw_hash = generate_password_hash(password)  # scrypt with random salt
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, pw_hash, now()),
            )
    except sqlite3.IntegrityError:
        return error(409, "An account with this email already exists.")
    return jsonify({"id": cur.lastrowid, "email": email}), 201


@app.post("/api/login")
def login():
    data = json_body()
    if data is None:
        return error(400, "Request body must be a JSON object.")
    email = data.get("email")
    password = data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return error(400, "Both 'email' and 'password' are required.")
    email = email.strip().lower()[:MAX_EMAIL_LEN]
    if not login_ip_limiter.allow(client_ip()) or not login_email_limiter.allow(email):
        return error(429, "Too many login attempts. Please wait a few minutes.")
    if len(password) > MAX_PASSWORD_LEN:
        return error(401, "Incorrect email or password.")

    conn = db()
    user = conn.execute(
        "SELECT id, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    stored = user["password_hash"] if user else _DUMMY_HASH
    ok = check_password_hash(stored, password)
    if not user or not ok:
        return error(401, "Incorrect email or password.")

    token = secrets.token_urlsafe(32)
    t = now()
    with conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (t,))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (hash_token(token), user["id"], t, t + SESSION_TTL_SECONDS),
        )
    return jsonify({"token": token, "expires_at": t + SESSION_TTL_SECONDS})


@app.post("/api/logout")
@require_auth
def logout():
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (g.token_hash,))
    return jsonify({"ok": True})


@app.get("/api/me")
@require_auth
def me():
    row = db().execute("SELECT id, email FROM users WHERE id = ?", (g.user_id,)).fetchone()
    return jsonify({"id": row["id"], "email": row["email"]})


# ---------------------------------------------------------------- notes API


@app.get("/api/notes")
@require_auth
def list_notes():
    rows = db().execute(
        "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
        (g.user_id,),
    ).fetchall()
    return jsonify([note_json(r) for r in rows])


@app.post("/api/notes")
@require_auth
def create_note():
    fields, err = validate_note(json_body())
    if err:
        return error(400, err)
    title, body = fields
    t = now()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO notes (user_id, title, body, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (g.user_id, title, body, t, t),
        )
    return jsonify(note_json(get_own_note(cur.lastrowid))), 201


@app.get("/api/notes/<int:note_id>")
@require_auth
def get_note(note_id):
    row = get_own_note(note_id)
    if row is None:
        return error(404, "Note not found.")
    return jsonify(note_json(row))


@app.put("/api/notes/<int:note_id>")
@require_auth
def update_note(note_id):
    fields, err = validate_note(json_body())
    if err:
        return error(400, err)
    title, body = fields
    with db() as conn:
        cur = conn.execute(
            "UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (title, body, now(), note_id, g.user_id),
        )
    if cur.rowcount == 0:
        return error(404, "Note not found.")
    return jsonify(note_json(get_own_note(note_id)))


@app.delete("/api/notes/<int:note_id>")
@require_auth
def delete_note(note_id):
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id)
        )
    if cur.rowcount == 0:
        return error(404, "Note not found.")
    return jsonify({"ok": True})


@app.post("/api/notes/<int:note_id>/share")
@require_auth
def share_note(note_id):
    """Return the note's share token, creating one if it doesn't have one yet."""
    row = get_own_note(note_id)
    if row is None:
        return error(404, "Note not found.")
    token = row["share_token"]
    if not token:
        token = secrets.token_urlsafe(24)
        with db() as conn:
            conn.execute(
                "UPDATE notes SET share_token = ? WHERE id = ? AND user_id = ?",
                (token, note_id, g.user_id),
            )
    return jsonify({"share_token": token, "url": request.host_url + "s/" + token})


@app.delete("/api/notes/<int:note_id>/share")
@require_auth
def unshare_note(note_id):
    """Turn off sharing; the old link stops working."""
    with db() as conn:
        cur = conn.execute(
            "UPDATE notes SET share_token = NULL WHERE id = ? AND user_id = ?",
            (note_id, g.user_id),
        )
    if cur.rowcount == 0:
        return error(404, "Note not found.")
    return jsonify({"ok": True})


@app.get("/api/shared/<share_token>")
def get_shared(share_token):
    if not shared_ip_limiter.allow(client_ip()):
        return error(429, "Too many requests. Please slow down.")
    if not SHARE_TOKEN_RE.match(share_token):
        return error(404, "Shared note not found.")
    row = db().execute(
        "SELECT * FROM notes WHERE share_token = ?", (share_token,)
    ).fetchone()
    if row is None:
        return error(404, "Shared note not found.")
    out = note_json(row, include_share=False)
    del out["id"]
    return jsonify(out)


# ---------------------------------------------------------------- web pages


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/s/<share_token>")
def shared_page(share_token):  # the page's script reads the token from the URL
    return send_from_directory(STATIC_DIR, "shared.html")


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


# ---------------------------------------------------------------- errors & headers


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if request.path.startswith("/api/"):
        return error(exc.code, exc.description or exc.name)
    return exc


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("Unhandled error")
    if request.path.startswith("/api/"):
        return error(500, "Internal server error.")
    return "Internal server error", 500


@app.after_request
def security_headers(resp):
    h = resp.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    h["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    if request.is_secure:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.path.startswith("/api/") or request.path.startswith("/s/"):
        h["Cache-Control"] = "no-store"
    resp.headers.pop("Server", None)
    return resp


init_db()

if __name__ == "__main__":
    from waitress import serve

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"NoteShare running on http://{host}:{port}")
    serve(app, host=host, port=port, ident=None, trusted_proxy=None)
