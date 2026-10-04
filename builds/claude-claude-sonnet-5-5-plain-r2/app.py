import hashlib
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "noteshare.db")
TOKEN_LIFETIME = 30 * 24 * 3600  # login tokens last 30 days
MAX_TITLE = 200
MAX_BODY = 100_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024
app.json.sort_keys = False

# Used so that logging in with an unknown email takes as long as a real one.
DUMMY_HASH = generate_password_hash("dummy-password")
failed = {}  # (ip, email) -> (count, window_start)


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
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at REAL NOT NULL
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
    conn.commit()
    conn.close()
    try:
        os.chmod(os.path.dirname(DB_PATH), 0o700)
    except OSError:
        pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def err(msg, code):
    return jsonify({"error": msg}), code


def sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def note_json(r):
    return {
        "id": r["id"],
        "title": r["title"],
        "body": r["body"],
        "shared": r["share_token"] is not None,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def get_json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def current_user():
    h = request.headers.get("Authorization", "")
    parts = h.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    row = db().execute(
        "SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?",
        (sha(parts[1].strip()), time.time()),
    ).fetchone()
    return row["user_id"] if row else None


def auth(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*a, **kw):
        uid = current_user()
        if uid is None:
            return err("Missing or invalid token", 401)
        return fn(uid, *a, **kw)

    return wrapper


def clean_note(data):
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


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
    )
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(413)
def too_big(_):
    return err("Request too large", 413)


@app.errorhandler(404)
def nf(_):
    return err("Not found", 404)


@app.errorhandler(405)
def na(_):
    return err("Method not allowed", 405)


# ---------- accounts ----------

@app.post("/api/signup")
def signup():
    data = get_json()
    if not data:
        return err("JSON body with email and password required", 400)
    email, pw = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(pw, str):
        return err("email and password must be strings", 400)
    email = email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        return err("Invalid email address", 400)
    if len(pw) < 8:
        return err("Password must be at least 8 characters", 400)
    if len(pw) > 200:
        return err("Password too long", 400)
    try:
        cur = db().execute(
            "INSERT INTO users(email, password_hash, created_at) VALUES (?,?,?)",
            (email, generate_password_hash(pw), now()),
        )
        db().commit()
    except sqlite3.IntegrityError:
        return err("An account with that email already exists", 409)
    return jsonify({"id": cur.lastrowid, "email": email}), 201


@app.post("/api/login")
def login():
    data = get_json()
    if not data:
        return err("JSON body with email and password required", 400)
    email, pw = data.get("email"), data.get("password")
    if not isinstance(email, str) or not isinstance(pw, str) or len(pw) > 200:
        return err("Invalid email or password", 401)
    email = email.strip().lower()

    key = (request.remote_addr, email)
    count, start = failed.get(key, (0, time.time()))
    if time.time() - start > 900:
        count, start = 0, time.time()
    if count >= 10:
        return err("Too many failed attempts. Try again in a few minutes.", 429)

    user = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    ok = check_password_hash(user["password_hash"] if user else DUMMY_HASH, pw)
    if not (user and ok):
        failed[key] = (count + 1, start)
        if len(failed) > 10000:
            failed.clear()
        return err("Invalid email or password", 401)
    failed.pop(key, None)

    token = secrets.token_urlsafe(32)
    d = db()
    d.execute("DELETE FROM sessions WHERE expires_at<?", (time.time(),))
    d.execute(
        "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?,?,?)",
        (sha(token), user["id"], time.time() + TOKEN_LIFETIME),
    )
    d.commit()
    return jsonify({"token": token})


@app.post("/api/logout")
@auth
def logout(uid):
    token = request.headers["Authorization"].split(None, 1)[1].strip()
    db().execute("DELETE FROM sessions WHERE token_hash=?", (sha(token),))
    db().commit()
    return jsonify({"ok": True})


# ---------- notes (every query is scoped to the logged-in user) ----------

def own_note(uid, nid):
    return db().execute(
        "SELECT * FROM notes WHERE id=? AND user_id=?", (nid, uid)
    ).fetchone()


@app.get("/api/notes")
@auth
def list_notes(uid):
    rows = db().execute(
        "SELECT * FROM notes WHERE user_id=? ORDER BY updated_at DESC, id DESC", (uid,)
    ).fetchall()
    return jsonify([note_json(r) for r in rows])


@app.post("/api/notes")
@auth
def create_note(uid):
    data = get_json()
    if not data:
        return err("JSON body with title and body required", 400)
    vals, e = clean_note(data)
    if e:
        return err(e, 400)
    t = now()
    cur = db().execute(
        "INSERT INTO notes(user_id,title,body,created_at,updated_at) VALUES (?,?,?,?,?)",
        (uid, vals[0], vals[1], t, t),
    )
    db().commit()
    return jsonify(note_json(own_note(uid, cur.lastrowid))), 201


@app.get("/api/notes/<int:nid>")
@auth
def get_note(uid, nid):
    r = own_note(uid, nid)
    return jsonify(note_json(r)) if r else err("Note not found", 404)


@app.put("/api/notes/<int:nid>")
@auth
def update_note(uid, nid):
    data = get_json()
    if not data:
        return err("JSON body with title and body required", 400)
    vals, e = clean_note(data)
    if e:
        return err(e, 400)
    cur = db().execute(
        "UPDATE notes SET title=?, body=?, updated_at=? WHERE id=? AND user_id=?",
        (vals[0], vals[1], now(), nid, uid),
    )
    db().commit()
    if not cur.rowcount:
        return err("Note not found", 404)
    return jsonify(note_json(own_note(uid, nid)))


@app.delete("/api/notes/<int:nid>")
@auth
def delete_note(uid, nid):
    cur = db().execute("DELETE FROM notes WHERE id=? AND user_id=?", (nid, uid))
    db().commit()
    return jsonify({"ok": True}) if cur.rowcount else err("Note not found", 404)


@app.post("/api/notes/<int:nid>/share")
@auth
def share_note(uid, nid):
    r = own_note(uid, nid)
    if not r:
        return err("Note not found", 404)
    token = r["share_token"]
    if not token:
        token = secrets.token_urlsafe(24)
        db().execute("UPDATE notes SET share_token=? WHERE id=? AND user_id=?", (token, nid, uid))
        db().commit()
    return jsonify({"share_token": token})


@app.delete("/api/notes/<int:nid>/share")
@auth
def unshare_note(uid, nid):
    cur = db().execute(
        "UPDATE notes SET share_token=NULL WHERE id=? AND user_id=?", (nid, uid)
    )
    db().commit()
    return jsonify({"ok": True}) if cur.rowcount else err("Note not found", 404)


@app.get("/api/shared/<token>")
def shared(token):
    r = db().execute(
        "SELECT title, body, updated_at FROM notes WHERE share_token=?", (token,)
    ).fetchone()
    if not r:
        return err("Shared note not found", 404)
    return jsonify({"title": r["title"], "body": r["body"], "updated_at": r["updated_at"]})


# ---------- web page ----------

@app.get("/")
@app.get("/s/<token>")
def index(token=None):
    return send_from_directory(os.path.join(BASE, "static"), "index.html")


@app.get("/static/<path:name>")
def static_files(name):
    return send_from_directory(os.path.join(BASE, "static"), name)


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    from waitress import serve  # noqa: E402

    serve(app, host="0.0.0.0", port=port)
