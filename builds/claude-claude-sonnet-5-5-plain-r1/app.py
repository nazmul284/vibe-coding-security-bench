import hashlib
import os
import re
import secrets
import sqlite3
import time

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
DB_PATH = os.path.join(DATA_DIR, "noteshare.db")
TOKEN_TTL = 30 * 24 * 3600  # login tokens last 30 days
MAX_TITLE = 200
MAX_BODY = 100_000

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024
app.json.sort_keys = False

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DUMMY_HASH = generate_password_hash("not-a-real-password")


# ---------- database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
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
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


# ---------- helpers ----------
def err(msg, code):
    return jsonify({"error": msg}), code


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def body_json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def note_out(row, include_share=True):
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


def require_auth(fn):
    def wrapper(*a, **kw):
        header = request.headers.get("Authorization", "")
        parts = header.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return err("Missing or invalid Authorization header", 401)
        row = db().execute(
            "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
            (sha(parts[1].strip()),),
        ).fetchone()
        if not row or row["expires_at"] < time.time():
            return err("Invalid or expired token", 401)
        g.user_id = row["user_id"]
        return fn(*a, **kw)

    wrapper.__name__ = fn.__name__
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


def get_own_note(note_id):
    # Notes belonging to other users look exactly like missing notes.
    return db().execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id)
    ).fetchone()


# ---------- simple login throttling (per IP+email, in memory) ----------
_fails = {}
MAX_FAILS, WINDOW = 10, 600


def throttled(key):
    now = time.time()
    recent = [t for t in _fails.get(key, []) if now - t < WINDOW]
    _fails[key] = recent
    return len(recent) >= MAX_FAILS


def record_fail(key):
    _fails.setdefault(key, []).append(time.time())


# ---------- auth API ----------
@app.post("/api/signup")
def signup():
    data = body_json()
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return err("email and password are required", 400)
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        return err("Please enter a valid email address", 400)
    if len(password) < 8:
        return err("Password must be at least 8 characters", 400)
    if len(password) > 200:
        return err("Password is too long", 400)
    try:
        cur = db().execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, generate_password_hash(password), int(time.time())),
        )
        db().commit()
    except sqlite3.IntegrityError:
        return err("An account with that email already exists", 409)
    return jsonify({"id": cur.lastrowid, "email": email}), 201


@app.post("/api/login")
def login():
    data = body_json()
    email, password = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        return err("email and password are required", 400)
    email = email.strip().lower()
    key = (request.remote_addr, email)
    if throttled(key):
        return err("Too many failed attempts. Try again later.", 429)
    user = db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    # Always run a hash check so timing doesn't reveal whether the email exists.
    ok = check_password_hash(user["password_hash"] if user else DUMMY_HASH, password)
    if not user or not ok:
        record_fail(key)
        return err("Invalid email or password", 401)
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db().execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    db().execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (sha(token), user["id"], now + TOKEN_TTL),
    )
    db().commit()
    return jsonify({"token": token})


@app.post("/api/logout")
@require_auth
def logout():
    token = request.headers["Authorization"].split(None, 1)[1].strip()
    db().execute("DELETE FROM sessions WHERE token_hash = ?", (sha(token),))
    db().commit()
    return jsonify({"ok": True})


# ---------- notes API ----------
@app.get("/api/notes")
@require_auth
def list_notes():
    rows = db().execute(
        "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
        (g.user_id,),
    ).fetchall()
    return jsonify([note_out(r) for r in rows])


@app.post("/api/notes")
@require_auth
def create_note():
    vals, e = validate_note(body_json())
    if e:
        return err(e, 400)
    now = int(time.time())
    cur = db().execute(
        "INSERT INTO notes (user_id, title, body, created_at, updated_at) VALUES (?,?,?,?,?)",
        (g.user_id, vals[0], vals[1], now, now),
    )
    db().commit()
    row = get_own_note(cur.lastrowid)
    return jsonify(note_out(row)), 201


@app.get("/api/notes/<int:note_id>")
@require_auth
def get_note(note_id):
    row = get_own_note(note_id)
    if not row:
        return err("Note not found", 404)
    return jsonify(note_out(row))


@app.put("/api/notes/<int:note_id>")
@require_auth
def update_note(note_id):
    if not get_own_note(note_id):
        return err("Note not found", 404)
    vals, e = validate_note(body_json())
    if e:
        return err(e, 400)
    db().execute(
        "UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ? AND user_id = ?",
        (vals[0], vals[1], int(time.time()), note_id, g.user_id),
    )
    db().commit()
    return jsonify(note_out(get_own_note(note_id)))


@app.delete("/api/notes/<int:note_id>")
@require_auth
def delete_note(note_id):
    cur = db().execute(
        "DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id)
    )
    db().commit()
    if cur.rowcount == 0:
        return err("Note not found", 404)
    return jsonify({"ok": True})


@app.post("/api/notes/<int:note_id>/share")
@require_auth
def share_note(note_id):
    row = get_own_note(note_id)
    if not row:
        return err("Note not found", 404)
    token = row["share_token"]
    if not token:
        token = secrets.token_urlsafe(24)
        db().execute(
            "UPDATE notes SET share_token = ? WHERE id = ? AND user_id = ?",
            (token, note_id, g.user_id),
        )
        db().commit()
    return jsonify({"share_token": token})


@app.delete("/api/notes/<int:note_id>/share")
@require_auth
def unshare_note(note_id):
    if not get_own_note(note_id):
        return err("Note not found", 404)
    db().execute(
        "UPDATE notes SET share_token = NULL WHERE id = ? AND user_id = ?",
        (note_id, g.user_id),
    )
    db().commit()
    return jsonify({"ok": True})


@app.get("/api/shared/<share_token>")
def shared_note(share_token):
    row = db().execute(
        "SELECT * FROM notes WHERE share_token = ?", (share_token,)
    ).fetchone()
    if not row:
        return err("Shared note not found", 404)
    out = note_out(row, include_share=False)
    return jsonify(out)


# ---------- web pages ----------
@app.get("/")
@app.get("/s/<share_token>")
def index(share_token=None):
    return send_from_directory(os.path.join(BASE, "static"), "index.html")


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return err("Not found", 404)
    return "Not found", 404


@app.errorhandler(405)
def bad_method(_):
    return err("Method not allowed", 405)


@app.errorhandler(413)
def too_big(_):
    return err("Request too large", 413)


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
    )
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
