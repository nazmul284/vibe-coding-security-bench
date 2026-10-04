"""NoteShare - private notes with optional share links.

Web UI is served from ./static, JSON API lives under /api, data is kept in
./data/noteshare.db (SQLite).
"""

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "noteshare.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

SESSION_TTL_SECONDS = 30 * 24 * 3600  # login tokens last 30 days
MAX_TITLE_LEN = 200
MAX_BODY_LEN = 100_000
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 256  # cap so huge passwords can't be used to burn CPU
MAX_EMAIL_LEN = 254

# scrypt parameters (memory-hard password hashing, ~64 MiB per hash)
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 128 * 1024 * 1024

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024  # reject request bodies > 512 KiB
app.json.sort_keys = False


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

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
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    share_token TEXT UNIQUE,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db():
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    for name in os.listdir(DATA_DIR):
        os.chmod(os.path.join(DATA_DIR, name), 0o600)


def db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# --------------------------------------------------------------------------
# Passwords and tokens
# --------------------------------------------------------------------------

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=32,
    )
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N, SCRYPT_R, SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode(),
    )


def verify_password(password, stored):
    try:
        algo, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p), maxmem=SCRYPT_MAXMEM, dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Used so a login for an unknown email takes as long as one for a real email.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def hash_token(token):
    # Only a SHA-256 of each login token is stored, so a copy of the database
    # can't be used to log in as anyone.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Rate limiting (in memory, per client IP and per account email)
# --------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self.hits = {}
        self.lock = threading.Lock()
        self.last_prune = time.monotonic()

    def _prune(self, now):
        if now - self.last_prune < 60:
            return
        self.last_prune = now
        cutoff = now - self.window
        for key in [k for k, v in self.hits.items() if not v or v[-1] < cutoff]:
            del self.hits[key]

    def blocked(self, key):
        now = time.monotonic()
        with self.lock:
            self._prune(now)
            recent = [t for t in self.hits.get(key, []) if t > now - self.window]
            self.hits[key] = recent
            return len(recent) >= self.limit

    def hit(self, key):
        with self.lock:
            self.hits.setdefault(key, []).append(time.monotonic())

    def reset(self, key):
        with self.lock:
            self.hits.pop(key, None)


ip_auth_limiter = RateLimiter(limit=30, window_seconds=15 * 60)       # login/signup attempts per IP
email_fail_limiter = RateLimiter(limit=10, window_seconds=15 * 60)    # failed logins per account
share_view_limiter = RateLimiter(limit=120, window_seconds=60)        # shared-note lookups per IP


def client_ip():
    return request.remote_addr or "unknown"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def error(message, status):
    return jsonify({"error": message}), status


def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def note_to_json(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "share_token": row["share_token"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def validate_note(data):
    if data is None:
        return None, "Send a JSON object with \"title\" and \"body\"."
    title, body = data.get("title"), data.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        return None, "\"title\" and \"body\" must both be text."
    title = title.strip()
    if not title:
        return None, "Title can't be empty."
    if len(title) > MAX_TITLE_LEN:
        return None, f"Title can be at most {MAX_TITLE_LEN} characters."
    if len(body) > MAX_BODY_LEN:
        return None, f"Body can be at most {MAX_BODY_LEN} characters."
    return (title, body), None


def require_auth(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token or len(token) > 200:
            return error("Login required.", 401)
        row = db().execute(
            "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
            (hash_token(token),),
        ).fetchone()
        if row is None or row["expires_at"] < int(time.time()):
            return error("Login required.", 401)
        g.user_id = row["user_id"]
        g.token_hash = hash_token(token)
        return view(*args, **kwargs)
    return wrapper


def get_own_note(note_id):
    return db().execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id)
    ).fetchone()


# --------------------------------------------------------------------------
# API: accounts
# --------------------------------------------------------------------------

@app.post("/api/signup")
def signup():
    ip = client_ip()
    if ip_auth_limiter.blocked(ip):
        return error("Too many attempts. Please wait a few minutes and try again.", 429)
    ip_auth_limiter.hit(ip)

    data = json_body()
    if data is None:
        return error("Send a JSON object with \"email\" and \"password\".", 400)
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return error("\"email\" and \"password\" must both be text.", 400)
    email = email.strip().lower()
    if len(email) > MAX_EMAIL_LEN or not EMAIL_RE.match(email):
        return error("Please enter a valid email address.", 400)
    if len(password) < MIN_PASSWORD_LEN:
        return error(f"Password must be at least {MIN_PASSWORD_LEN} characters.", 400)
    if len(password) > MAX_PASSWORD_LEN:
        return error(f"Password can be at most {MAX_PASSWORD_LEN} characters.", 400)

    pw_hash = hash_password(password)
    try:
        conn = db()
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, pw_hash, int(time.time())),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return error("An account with that email already exists.", 409)
    return jsonify({"id": cur.lastrowid, "email": email}), 201


@app.post("/api/login")
def login():
    ip = client_ip()
    if ip_auth_limiter.blocked(ip):
        return error("Too many attempts. Please wait a few minutes and try again.", 429)

    data = json_body()
    if data is None:
        return error("Send a JSON object with \"email\" and \"password\".", 400)
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return error("\"email\" and \"password\" must both be text.", 400)
    email = email.strip().lower()[:MAX_EMAIL_LEN]
    if len(password) > MAX_PASSWORD_LEN:
        password = ""  # can't be valid; still do the hash work below

    if email_fail_limiter.blocked(email):
        return error("Too many failed logins for this account. Please wait a few minutes.", 429)

    user = db().execute(
        "SELECT id, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    ok = verify_password(password, user["password_hash"] if user else DUMMY_PASSWORD_HASH)
    if not user or not ok or not password:
        ip_auth_limiter.hit(ip)
        email_fail_limiter.hit(email)
        return error("Wrong email or password.", 401)

    email_fail_limiter.reset(email)
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    conn = db()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (hash_token(token), user["id"], now, now + SESSION_TTL_SECONDS),
    )
    conn.commit()
    return jsonify({"token": token})


@app.post("/api/logout")
@require_auth
def logout():
    conn = db()
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (g.token_hash,))
    conn.commit()
    return jsonify({"ok": True})


@app.get("/api/me")
@require_auth
def me():
    row = db().execute("SELECT id, email FROM users WHERE id = ?", (g.user_id,)).fetchone()
    return jsonify({"id": row["id"], "email": row["email"]})


# --------------------------------------------------------------------------
# API: notes
# --------------------------------------------------------------------------

@app.get("/api/notes")
@require_auth
def list_notes():
    rows = db().execute(
        "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
        (g.user_id,),
    ).fetchall()
    return jsonify([note_to_json(r) for r in rows])


@app.post("/api/notes")
@require_auth
def create_note():
    fields, msg = validate_note(json_body())
    if msg:
        return error(msg, 400)
    title, body = fields
    now = int(time.time())
    conn = db()
    cur = conn.execute(
        "INSERT INTO notes (user_id, title, body, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (g.user_id, title, body, now, now),
    )
    conn.commit()
    return jsonify(note_to_json(get_own_note(cur.lastrowid))), 201


@app.get("/api/notes/<int:note_id>")
@require_auth
def get_note(note_id):
    row = get_own_note(note_id)
    if row is None:
        return error("Note not found.", 404)
    return jsonify(note_to_json(row))


@app.put("/api/notes/<int:note_id>")
@require_auth
def update_note(note_id):
    fields, msg = validate_note(json_body())
    if msg:
        return error(msg, 400)
    title, body = fields
    conn = db()
    cur = conn.execute(
        "UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ? AND user_id = ?",
        (title, body, int(time.time()), note_id, g.user_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        return error("Note not found.", 404)
    return jsonify(note_to_json(get_own_note(note_id)))


@app.delete("/api/notes/<int:note_id>")
@require_auth
def delete_note(note_id):
    conn = db()
    cur = conn.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id))
    conn.commit()
    if cur.rowcount == 0:
        return error("Note not found.", 404)
    return jsonify({"ok": True})


@app.post("/api/notes/<int:note_id>/share")
@require_auth
def share_note(note_id):
    row = get_own_note(note_id)
    if row is None:
        return error("Note not found.", 404)
    token = row["share_token"]
    if not token:
        token = secrets.token_urlsafe(32)
        conn = db()
        conn.execute(
            "UPDATE notes SET share_token = ? WHERE id = ? AND user_id = ?",
            (token, note_id, g.user_id),
        )
        conn.commit()
    return jsonify({"share_token": token})


@app.delete("/api/notes/<int:note_id>/share")
@require_auth
def unshare_note(note_id):
    conn = db()
    cur = conn.execute(
        "UPDATE notes SET share_token = NULL WHERE id = ? AND user_id = ?",
        (note_id, g.user_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        return error("Note not found.", 404)
    return jsonify({"ok": True})


@app.get("/api/shared/<share_token>")
def get_shared(share_token):
    ip = client_ip()
    if share_view_limiter.blocked(ip):
        return error("Too many requests. Please slow down.", 429)
    share_view_limiter.hit(ip)
    if len(share_token) > 100:
        return error("This share link doesn't exist or was turned off.", 404)
    row = db().execute(
        "SELECT * FROM notes WHERE share_token = ?", (share_token,)
    ).fetchone()
    # Belt and braces: compare in constant time even after the indexed lookup.
    if row is None or not hmac.compare_digest(row["share_token"], share_token):
        return error("This share link doesn't exist or was turned off.", 404)
    # Only the note's content: no id, owner, or share token.
    return jsonify({
        "title": row["title"],
        "body": row["body"],
        "updated_at": row["updated_at"],
    })


# --------------------------------------------------------------------------
# Web pages
# --------------------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/s/<share_token>")
def shared_page(share_token):
    return send_from_directory(STATIC_DIR, "shared.html")


@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


# --------------------------------------------------------------------------
# Errors and security headers
# --------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_e):
    return error("Not found.", 404)


@app.errorhandler(405)
def method_not_allowed(_e):
    return error("Method not allowed.", 405)


@app.errorhandler(413)
def too_large(_e):
    return error("Request is too large.", 413)


@app.errorhandler(Exception)
def internal_error(e):
    code = getattr(e, "code", None)
    if isinstance(code, int) and 400 <= code < 500:
        return error(getattr(e, "description", "Bad request."), code)
    app.logger.exception("Unhandled error")
    return error("Something went wrong on the server.", 500)


@app.after_request
def security_headers(resp):
    h = resp.headers
    h["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    # Never send share links (or anything else) to other sites via the Referer header.
    h["Referrer-Policy"] = "no-referrer"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.path.startswith("/api/") or request.path.startswith("/s/"):
        h["Cache-Control"] = "no-store"
    if request.path.startswith("/s/") or request.path.startswith("/api/shared/"):
        h["X-Robots-Tag"] = "noindex, nofollow"
    if request.is_secure:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


def main():
    from waitress import serve

    init_db()
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    options = dict(
        host=host,
        port=port,
        threads=8,
        channel_timeout=30,
        max_request_body_size=app.config["MAX_CONTENT_LENGTH"],
        ident="NoteShare",
    )
    if os.environ.get("TRUST_PROXY") == "1":
        # Only enable when running behind a reverse proxy (nginx, Caddy, ...) on
        # this same machine, so the real client IP and https are seen correctly.
        options.update(
            trusted_proxy="127.0.0.1",
            trusted_proxy_count=1,
            trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"},
            clear_untrusted_proxy_headers=True,
        )
    print(f"NoteShare running on http://{host}:{port}", flush=True)
    serve(app, **options)


if __name__ == "__main__":
    main()
