"""NoteShare: private notes with optional share links. Web page + JSON API."""
import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "noteshare.db")

TOKEN_LIFETIME = 30 * 24 * 3600          # login tokens last 30 days
MAX_EMAIL, MAX_TITLE, MAX_BODY = 254, 200, 50_000
MIN_PASSWORD, MAX_PASSWORD = 10, 128
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
app.json.sort_keys = False


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            share_token TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS notes_user ON notes(user_id);
        """
    )
    db.execute("DELETE FROM tokens WHERE expires_at < ?", (int(time.time()),))
    db.commit()
    db.close()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(DB_PATH + suffix):
            os.chmod(DB_PATH + suffix, 0o600)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_token(token):
    # Tokens are 256-bit random values, so a fast hash is fine. Only the hash
    # is stored, so a leaked database does not leak usable tokens.
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------ rate limiting
class RateLimiter:
    """Simple in-memory sliding window limiter (single server process)."""

    def __init__(self):
        self.hits = {}
        self.lock = threading.Lock()

    def _recent(self, key, window):
        cutoff = time.time() - window
        hits = [t for t in self.hits.get(key, []) if t > cutoff]
        if hits:
            self.hits[key] = hits
        else:
            self.hits.pop(key, None)
        return hits

    def blocked(self, key, limit, window):
        with self.lock:
            return len(self._recent(key, window)) >= limit

    def record(self, key, window):
        with self.lock:
            hits = self._recent(key, window)
            hits.append(time.time())
            self.hits[key] = hits
            if len(self.hits) > 50_000:  # bound memory
                self.hits.clear()


limiter = RateLimiter()
WINDOW = 15 * 60


def too_many():
    return jsonify(error="Too many attempts. Please try again later."), 429


# ----------------------------------------------------------------- helpers
def err(message, status):
    return jsonify(error=message), status


def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def note_json(row, owner=True):
    if not owner:
        return {"title": row["title"], "body": row["body"],
                "updated_at": row["updated_at"]}
    return {"id": row["id"], "title": row["title"], "body": row["body"],
            "share_token": row["share_token"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return err("Authentication required.", 401)
        row = get_db().execute(
            "SELECT user_id, token_hash FROM tokens "
            "WHERE token_hash = ? AND expires_at > ?",
            (hash_token(token.strip()), int(time.time())),
        ).fetchone()
        if row is None:
            return err("Invalid or expired token.", 401)
        g.user_id = row["user_id"]
        g.token_hash = row["token_hash"]
        return fn(*args, **kwargs)
    return wrapper


def valid_text(value, max_len, allow_empty=False):
    if not isinstance(value, str) or len(value) > max_len:
        return False
    return allow_empty or bool(value.strip())


def get_own_note(note_id):
    return get_db().execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id)
    ).fetchone()


# ----------------------------------------------------- security headers etc.
@app.after_request
def secure_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"  # share tokens live in URLs
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(404)
def not_found(_e):
    return err("Not found.", 404)


@app.errorhandler(405)
def bad_method(_e):
    return err("Method not allowed.", 405)


@app.errorhandler(413)
def too_big(_e):
    return err("Request too large.", 413)


@app.errorhandler(Exception)
def unexpected(e):
    if hasattr(e, "code") and isinstance(e.code, int) and e.code < 500:
        return err(getattr(e, "description", "Bad request."), e.code)
    app.logger.exception("Unhandled error")
    return err("Internal server error.", 500)


# -------------------------------------------------------------------- auth
DUMMY_HASH = generate_password_hash("not-a-real-password")


@app.post("/api/signup")
def signup():
    ip = request.remote_addr or "?"
    if limiter.blocked(("signup", ip), 10, WINDOW):
        return too_many()
    data = json_body()
    if data is None:
        return err("Send a JSON object.", 400)
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or len(email) > MAX_EMAIL \
            or not EMAIL_RE.match(email.strip()):
        return err("Please provide a valid email address.", 400)
    if not isinstance(password, str) or not (MIN_PASSWORD <= len(password) <= MAX_PASSWORD):
        return err(f"Password must be {MIN_PASSWORD}-{MAX_PASSWORD} characters.", 400)
    limiter.record(("signup", ip), WINDOW)
    email = email.strip().lower()
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, generate_password_hash(password), now_iso()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return err("An account with that email already exists.", 409)
    return jsonify(id=cur.lastrowid, email=email), 201


@app.post("/api/login")
def login():
    ip = request.remote_addr or "?"
    data = json_body()
    if data is None:
        return err("Send a JSON object.", 400)
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str) \
            or len(email) > MAX_EMAIL or len(password) > MAX_PASSWORD:
        return err("Invalid email or password.", 401)
    email = email.strip().lower()
    # Throttle guessing per client address and per account.
    if limiter.blocked(("login-ip", ip), 30, WINDOW) \
            or limiter.blocked(("login-email", email, ip), 8, WINDOW):
        return too_many()

    db = get_db()
    user = db.execute("SELECT id, password_hash FROM users WHERE email = ?",
                      (email,)).fetchone()
    # Always run a hash check so response time doesn't reveal whether the email exists.
    ok = check_password_hash(user["password_hash"] if user else DUMMY_HASH, password)
    if not (user and ok):
        limiter.record(("login-ip", ip), WINDOW)
        limiter.record(("login-email", email, ip), WINDOW)
        return err("Invalid email or password.", 401)

    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO tokens (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
               (hash_token(token), user["id"], int(time.time()) + TOKEN_LIFETIME))
    db.execute("DELETE FROM tokens WHERE expires_at < ?", (int(time.time()),))
    db.commit()
    return jsonify(token=token)


@app.post("/api/logout")
@require_auth
def logout():
    db = get_db()
    db.execute("DELETE FROM tokens WHERE token_hash = ?", (g.token_hash,))
    db.commit()
    return jsonify(ok=True)


# ------------------------------------------------------------------- notes
@app.get("/api/notes")
@require_auth
def list_notes():
    rows = get_db().execute(
        "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
        (g.user_id,)).fetchall()
    return jsonify([note_json(r) for r in rows])


@app.post("/api/notes")
@require_auth
def create_note():
    data = json_body()
    if data is None:
        return err("Send a JSON object.", 400)
    title, body = data.get("title"), data.get("body", "")
    if not valid_text(title, MAX_TITLE):
        return err(f"Title is required (max {MAX_TITLE} characters).", 400)
    if not valid_text(body, MAX_BODY, allow_empty=True):
        return err(f"Body must be text (max {MAX_BODY} characters).", 400)
    db = get_db()
    ts = now_iso()
    cur = db.execute(
        "INSERT INTO notes (user_id, title, body, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)", (g.user_id, title.strip(), body, ts, ts))
    db.commit()
    return jsonify(note_json(get_own_note(cur.lastrowid))), 201


# Other people's notes get the same 404 as missing notes, so ids reveal nothing.
@app.get("/api/notes/<int:note_id>")
@require_auth
def get_note(note_id):
    row = get_own_note(note_id)
    return jsonify(note_json(row)) if row else err("Note not found.", 404)


@app.put("/api/notes/<int:note_id>")
@require_auth
def update_note(note_id):
    row = get_own_note(note_id)
    if not row:
        return err("Note not found.", 404)
    data = json_body()
    if data is None:
        return err("Send a JSON object.", 400)
    title = data.get("title", row["title"])
    body = data.get("body", row["body"])
    if not valid_text(title, MAX_TITLE):
        return err(f"Title is required (max {MAX_TITLE} characters).", 400)
    if not valid_text(body, MAX_BODY, allow_empty=True):
        return err(f"Body must be text (max {MAX_BODY} characters).", 400)
    db = get_db()
    db.execute("UPDATE notes SET title = ?, body = ?, updated_at = ? "
               "WHERE id = ? AND user_id = ?",
               (title.strip(), body, now_iso(), note_id, g.user_id))
    db.commit()
    return jsonify(note_json(get_own_note(note_id)))


@app.delete("/api/notes/<int:note_id>")
@require_auth
def delete_note(note_id):
    db = get_db()
    cur = db.execute("DELETE FROM notes WHERE id = ? AND user_id = ?",
                     (note_id, g.user_id))
    db.commit()
    return jsonify(ok=True) if cur.rowcount else err("Note not found.", 404)


@app.post("/api/notes/<int:note_id>/share")
@require_auth
def share_note(note_id):
    row = get_own_note(note_id)
    if not row:
        return err("Note not found.", 404)
    token = row["share_token"]
    if not token:
        token = secrets.token_urlsafe(32)
        db = get_db()
        db.execute("UPDATE notes SET share_token = ? WHERE id = ? AND user_id = ?",
                   (token, note_id, g.user_id))
        db.commit()
    return jsonify(share_token=token)


@app.delete("/api/notes/<int:note_id>/share")
@require_auth
def unshare_note(note_id):
    db = get_db()
    cur = db.execute("UPDATE notes SET share_token = NULL WHERE id = ? AND user_id = ?",
                     (note_id, g.user_id))
    db.commit()
    return jsonify(ok=True) if cur.rowcount else err("Note not found.", 404)


@app.get("/api/shared/<share_token>")
def shared_note(share_token):
    ip = request.remote_addr or "?"
    if limiter.blocked(("shared", ip), 60, 60):
        return too_many()
    limiter.record(("shared", ip), 60)
    if not 20 <= len(share_token) <= 100:
        return err("Not found.", 404)
    row = get_db().execute("SELECT * FROM notes WHERE share_token = ?",
                           (share_token,)).fetchone()
    return jsonify(note_json(row, owner=False)) if row else err("Not found.", 404)


# ---------------------------------------------------------------- web page
STATIC_DIR = os.path.join(BASE_DIR, "static")


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/s/<share_token>")
def shared_page(share_token):
    return send_from_directory(STATIC_DIR, "shared.html")


@app.get("/static/<path:name>")
def static_files(name):
    return send_from_directory(STATIC_DIR, name)


init_db()

if __name__ == "__main__":
    from waitress import serve
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    print(f"NoteShare running on http://{host}:{port}")
    serve(app, host=host, port=port, max_request_body_size=app.config["MAX_CONTENT_LENGTH"])
