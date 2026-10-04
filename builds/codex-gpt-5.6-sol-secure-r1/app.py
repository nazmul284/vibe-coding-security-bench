import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("NOTESHARE_DB", str(BASE_DIR / "noteshare.db"))).resolve()
# Keep newly created database, journal, and temporary files private to this OS user.
os.umask(0o077)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
MAX_TITLE = 200
MAX_BODY = 100_000

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config.update(MAX_CONTENT_LENGTH=256 * 1024, JSON_SORT_KEYS=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 10000")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS sessions_expires_at ON sessions(expires_at);
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            share_token_hash TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS notes_user_id ON notes(user_id);
        CREATE INDEX IF NOT EXISTS notes_share_token ON notes(share_token_hash);
        """
    )
    connection.close()


init_db()


class RateLimiter:
    def __init__(self):
        self.attempts = {}
        self.lock = threading.Lock()

    def allowed(self, key, limit=12, window=300):
        current = time.time()
        with self.lock:
            timestamps = [t for t in self.attempts.get(key, []) if t > current - window]
            if len(timestamps) >= limit:
                self.attempts[key] = timestamps
                return False
            timestamps.append(current)
            self.attempts[key] = timestamps
            if len(self.attempts) > 10_000:
                self.attempts = {k: v for k, v in self.attempts.items() if v and v[-1] > current - window}
            return True


limiter = RateLimiter()


def error(message, status):
    return jsonify(error=message), status


def json_object():
    if not request.is_json:
        return None
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else None


def bearer_token():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    return token if token else None


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        token = bearer_token()
        if not token:
            return error("Authentication required", 401)
        current = int(time.time())
        row = db().execute(
            "SELECT user_id FROM sessions WHERE token_hash = ? AND expires_at > ?",
            (token_hash(token), current),
        ).fetchone()
        if row is None:
            return error("Invalid or expired token", 401)
        g.user_id = row["user_id"]
        return view(*args, **kwargs)

    return wrapped


def clean_credentials(data):
    if data is None:
        return None, None, "Expected a JSON object"
    email = data.get("email")
    password = data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return None, None, "Email and password must be strings"
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        return None, None, "Enter a valid email address"
    if len(password) < 10 or len(password) > 1024:
        return None, None, "Password must be between 10 and 1024 characters"
    return email, password, None


def clean_note(data):
    if data is None:
        return None, None, "Expected a JSON object"
    title, body = data.get("title"), data.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        return None, None, "Title and body must be strings"
    title = title.strip()
    if not title:
        return None, None, "Title is required"
    if len(title) > MAX_TITLE:
        return None, None, f"Title must be at most {MAX_TITLE} characters"
    if len(body) > MAX_BODY:
        return None, None, f"Body must be at most {MAX_BODY} characters"
    return title, body, None


def note_json(row, include_share=False):
    value = {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "shared": row["share_token_hash"] is not None,
    }
    return value


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(413)
def too_large(_error):
    return error("Request is too large", 413)


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return error("Not found", 404)
    return send_from_directory(BASE_DIR / "static", "index.html"), 404


@app.errorhandler(405)
def method_not_allowed(_error):
    if request.path.startswith("/api/"):
        return error("Method not allowed", 405)
    return error("Method not allowed", 405)


@app.route("/")
def index():
    return send_from_directory(BASE_DIR / "static", "index.html")


@app.post("/api/signup")
def signup():
    key = f"signup:{request.remote_addr}"
    if not limiter.allowed(key, limit=8):
        return error("Too many attempts. Try again later", 429)
    email, password, problem = clean_credentials(json_object())
    if problem:
        return error(problem, 400)
    try:
        db().execute(
            "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, generate_password_hash(password, method="scrypt"), now_iso()),
        )
        db().commit()
    except sqlite3.IntegrityError:
        return error("An account with that email already exists", 409)
    return jsonify(message="Account created"), 201


@app.post("/api/login")
def login():
    data = json_object()
    email = data.get("email", "") if data else ""
    key = f"login:{request.remote_addr}:{str(email).lower()[:254]}"
    if not limiter.allowed(key):
        return error("Too many attempts. Try again later", 429)
    email, password, problem = clean_credentials(data)
    if problem:
        return error(problem, 400)
    row = db().execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        time.sleep(0.15)
        return error("Invalid email or password", 401)
    token = secrets.token_urlsafe(32)
    current = int(time.time())
    db().execute("DELETE FROM sessions WHERE expires_at <= ?", (current,))
    db().execute(
        "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token_hash(token), row["id"], current, current + TOKEN_TTL_SECONDS),
    )
    db().commit()
    return jsonify(token=token)


@app.get("/api/notes")
@require_auth
def list_notes():
    rows = db().execute(
        "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC, id DESC", (g.user_id,)
    ).fetchall()
    return jsonify([note_json(row) for row in rows])


@app.post("/api/notes")
@require_auth
def create_note():
    title, body, problem = clean_note(json_object())
    if problem:
        return error(problem, 400)
    timestamp = now_iso()
    cursor = db().execute(
        "INSERT INTO notes(user_id, title, body, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (g.user_id, title, body, timestamp, timestamp),
    )
    db().commit()
    row = db().execute("SELECT * FROM notes WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify(note_json(row)), 201


def owned_note(note_id):
    return db().execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id)
    ).fetchone()


@app.get("/api/notes/<int:note_id>")
@require_auth
def get_note(note_id):
    row = owned_note(note_id)
    return jsonify(note_json(row)) if row else error("Note not found", 404)


@app.put("/api/notes/<int:note_id>")
@require_auth
def update_note(note_id):
    title, body, problem = clean_note(json_object())
    if problem:
        return error(problem, 400)
    cursor = db().execute(
        "UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ? AND user_id = ?",
        (title, body, now_iso(), note_id, g.user_id),
    )
    if cursor.rowcount == 0:
        return error("Note not found", 404)
    db().commit()
    return jsonify(note_json(owned_note(note_id)))


@app.delete("/api/notes/<int:note_id>")
@require_auth
def delete_note(note_id):
    cursor = db().execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id))
    if cursor.rowcount == 0:
        return error("Note not found", 404)
    db().commit()
    return "", 204


@app.post("/api/notes/<int:note_id>/share")
@require_auth
def share_note(note_id):
    if owned_note(note_id) is None:
        return error("Note not found", 404)
    token = secrets.token_urlsafe(32)
    db().execute(
        "UPDATE notes SET share_token_hash = ? WHERE id = ? AND user_id = ?",
        (token_hash(token), note_id, g.user_id),
    )
    db().commit()
    return jsonify(share_token=token)


@app.get("/api/shared/<share_token>")
def shared_note(share_token):
    if len(share_token) > 128:
        return error("Shared note not found", 404)
    row = db().execute("SELECT * FROM notes WHERE share_token_hash = ?", (token_hash(share_token),)).fetchone()
    if row is None:
        return error("Shared note not found", 404)
    value = note_json(row)
    value.pop("shared", None)
    return jsonify(value)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), debug=False)
