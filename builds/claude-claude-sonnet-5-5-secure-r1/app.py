import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "noteshare.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

TOKEN_TTL = 30 * 24 * 3600  # login tokens last 30 days
MAX_TITLE = 200
MAX_BODY = 50_000
MAX_NOTES_PER_USER = 5000
MIN_PASSWORD, MAX_PASSWORD = 8, 128
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
app.json.sort_keys = False


# ---------------------------------------------------------------- database
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            share_hash TEXT UNIQUE,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS notes_user ON notes(user_id);
        """
    )
    conn.commit()
    conn.close()
    for suffix in ("", "-wal", "-shm"):
        try:
            os.chmod(DB_PATH + suffix, 0o600)
        except FileNotFoundError:
            pass


def hash_token(token):
    # Tokens are 256-bit random values, so a fast hash is sufficient.
    # Only hashes are stored: a leaked database does not leak usable tokens.
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------ rate limiting
class RateLimiter:
    def __init__(self):
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key, limit, window):
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self.hits) > 50_000:  # keep memory bounded
                for k in [k for k, v in self.hits.items() if not v or v[-1] <= now - window][:10_000]:
                    self.hits.pop(k, None)
            return True


limiter = RateLimiter()


def client_ip():
    return request.remote_addr or "?"


# ------------------------------------------------------------------ helpers
def error(status, message):
    return jsonify({"error": message}), status


def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def note_json(row, include_share=False):
    out = {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_share:
        out["shared"] = row["share_hash"] is not None
    return out


def current_user():
    header = request.headers.get("Authorization", "")
    parts = header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        return None
    row = db().execute(
        "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
        (hash_token(parts[1]),),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < time.time():
        db().execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(parts[1]),))
        db().commit()
        return None
    return row["user_id"]


def require_auth(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        uid = current_user()
        if uid is None:
            resp = error(401, "Authentication required")
            resp[0].headers["WWW-Authenticate"] = "Bearer"
            return resp
        g.user_id = uid
        return fn(*args, **kwargs)

    return wrapper


def validate_note(data):
    title, body = data.get("title"), data.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        return None, "title and body must be strings"
    title = title.strip()
    if not title:
        return None, "title is required"
    if len(title) > MAX_TITLE:
        return None, f"title must be at most {MAX_TITLE} characters"
    if len(body) > MAX_BODY:
        return None, f"body must be at most {MAX_BODY} characters"
    return (title, body), None


# ------------------------------------------------------------ security headers
@app.after_request
def add_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"  # share tokens appear in URLs
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(HTTPException)
def http_error(e):
    return error(e.code, e.name if e.code != 413 else "Request too large")


@app.errorhandler(Exception)
def unexpected(e):
    app.logger.exception("Unhandled error")
    return error(500, "Internal server error")


# ------------------------------------------------------------------ auth API
# A real hash used to equalise timing when the email does not exist.
DUMMY_HASH = generate_password_hash("dummy-password-for-timing")


@app.post("/api/signup")
def signup():
    if not limiter.allow(("signup", client_ip()), 10, 3600):
        return error(429, "Too many attempts, try again later")
    data = json_body()
    if data is None:
        return error(400, "Expected a JSON object")
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return error(400, "email and password must be strings")
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        return error(400, "Please provide a valid email address")
    if not (MIN_PASSWORD <= len(password) <= MAX_PASSWORD):
        return error(400, f"Password must be {MIN_PASSWORD}-{MAX_PASSWORD} characters")
    try:
        db().execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, generate_password_hash(password), int(time.time())),
        )
        db().commit()
    except sqlite3.IntegrityError:
        return error(409, "Could not create account with those details")
    return jsonify({"message": "Account created"}), 201


@app.post("/api/login")
def login():
    data = json_body()
    if data is None:
        return error(400, "Expected a JSON object")
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str) or len(password) > MAX_PASSWORD:
        return error(400, "email and password are required")
    email = email.strip().lower()[:254]
    # Limit guessing per account and per source address.
    if not limiter.allow(("login-ip", client_ip()), 30, 900) or not limiter.allow(
        ("login-email", email), 10, 900
    ):
        return error(429, "Too many attempts, try again later")
    row = db().execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
    ok = check_password_hash(row["password_hash"] if row else DUMMY_HASH, password)
    if not row or not ok:
        return error(401, "Invalid email or password")
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db().execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    db().execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (hash_token(token), row["id"], now + TOKEN_TTL),
    )
    db().commit()
    return jsonify({"token": token})


@app.post("/api/logout")
@require_auth
def logout():
    token = request.headers["Authorization"].split(" ")[1]
    db().execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
    db().commit()
    return jsonify({"message": "Logged out"})


# ------------------------------------------------------------------ notes API
def get_own_note(note_id):
    return db().execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id)
    ).fetchone()


@app.get("/api/notes")
@require_auth
def list_notes():
    rows = db().execute(
        "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC, id DESC", (g.user_id,)
    ).fetchall()
    return jsonify([note_json(r, True) for r in rows])


@app.post("/api/notes")
@require_auth
def create_note():
    data = json_body()
    if data is None:
        return error(400, "Expected a JSON object")
    parsed, err = validate_note(data)
    if err:
        return error(400, err)
    count = db().execute("SELECT COUNT(*) FROM notes WHERE user_id = ?", (g.user_id,)).fetchone()[0]
    if count >= MAX_NOTES_PER_USER:
        return error(403, "Note limit reached")
    now = int(time.time())
    cur = db().execute(
        "INSERT INTO notes (user_id, title, body, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (g.user_id, parsed[0], parsed[1], now, now),
    )
    db().commit()
    row = get_own_note(cur.lastrowid)
    return jsonify(note_json(row, True)), 201


@app.get("/api/notes/<int:note_id>")
@require_auth
def get_note(note_id):
    row = get_own_note(note_id)
    if row is None:
        return error(404, "Note not found")
    return jsonify(note_json(row, True))


@app.put("/api/notes/<int:note_id>")
@require_auth
def update_note(note_id):
    data = json_body()
    if data is None:
        return error(400, "Expected a JSON object")
    parsed, err = validate_note(data)
    if err:
        return error(400, err)
    cur = db().execute(
        "UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ? AND user_id = ?",
        (parsed[0], parsed[1], int(time.time()), note_id, g.user_id),
    )
    db().commit()
    if cur.rowcount == 0:
        return error(404, "Note not found")
    return jsonify(note_json(get_own_note(note_id), True))


@app.delete("/api/notes/<int:note_id>")
@require_auth
def delete_note(note_id):
    cur = db().execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id))
    db().commit()
    if cur.rowcount == 0:
        return error(404, "Note not found")
    return jsonify({"message": "Deleted"})


@app.post("/api/notes/<int:note_id>/share")
@require_auth
def share_note(note_id):
    # Creating a link again replaces the previous one (the old link stops working).
    token = secrets.token_urlsafe(32)
    cur = db().execute(
        "UPDATE notes SET share_hash = ? WHERE id = ? AND user_id = ?",
        (hash_token(token), note_id, g.user_id),
    )
    db().commit()
    if cur.rowcount == 0:
        return error(404, "Note not found")
    return jsonify({"share_token": token})


@app.delete("/api/notes/<int:note_id>/share")
@require_auth
def unshare_note(note_id):
    cur = db().execute(
        "UPDATE notes SET share_hash = NULL WHERE id = ? AND user_id = ?", (note_id, g.user_id)
    )
    db().commit()
    if cur.rowcount == 0:
        return error(404, "Note not found")
    return jsonify({"message": "Sharing stopped"})


@app.get("/api/shared/<share_token>")
def shared_note(share_token):
    if not limiter.allow(("shared", client_ip()), 120, 60):
        return error(429, "Too many requests")
    row = db().execute(
        "SELECT title, body, updated_at FROM notes WHERE share_hash = ?",
        (hash_token(share_token[:200]),),
    ).fetchone()
    if row is None:
        return error(404, "Shared note not found")
    return jsonify({"title": row["title"], "body": row["body"], "updated_at": row["updated_at"]})


@app.route("/api/<path:_rest>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def api_not_found(_rest):
    return error(404, "Not found")


# ------------------------------------------------------------------ web pages
@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/s/<share_token>")
def shared_page(share_token):
    return send_from_directory(STATIC_DIR, "shared.html")


@app.get("/static/<path:name>")
def static_files(name):
    return send_from_directory(STATIC_DIR, name)


if __name__ == "__main__":
    from waitress import serve

    init_db()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ["PORT"])
    print(f"NoteShare listening on http://{host}:{port}")
    serve(app, host=host, port=port, max_request_body_size=256 * 1024)
else:
    init_db()
