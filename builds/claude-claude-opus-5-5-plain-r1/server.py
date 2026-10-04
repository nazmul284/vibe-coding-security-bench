"""NoteShare - a tiny note-taking app with share links.

Uses only the Python standard library. Data is stored in data/noteshare.db.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "noteshare.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

SESSION_LIFETIME = 30 * 24 * 3600  # 30 days
MAX_BODY_BYTES = 1_000_000
MAX_TITLE_LEN = 200
MAX_NOTE_LEN = 100_000
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 1024
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Login throttling: max failed attempts per (ip) and per (email) in a window.
LOGIN_WINDOW = 15 * 60
LOGIN_MAX_FAILS = 10
_fail_lock = threading.Lock()
_failures = {}  # key -> list of timestamps

# ---------------------------------------------------------------- database

_local = threading.local()


def db():
    """Connection for the current request; closed by close_db() when it ends."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


def close_db():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        _local.conn = None
        conn.close()  # rolls back anything left uncommitted


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = db()
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
            share_token TEXT UNIQUE,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS notes_user ON notes(user_id);
        """
    )
    conn.commit()
    close_db()


# ---------------------------------------------------------------- security helpers


def hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$%s$%s" % (salt.hex(), dk.hex())


def verify_password(password, stored):
    try:
        _, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# Used so that logins for unknown emails take the same time as wrong passwords.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def sha256(s):
    return hashlib.sha256(s.encode()).hexdigest()


def too_many_failures(*keys):
    now = time.time()
    with _fail_lock:
        for k in keys:
            recent = [t for t in _failures.get(k, []) if now - t < LOGIN_WINDOW]
            _failures[k] = recent
            if len(recent) >= LOGIN_MAX_FAILS:
                return True
    return False


def record_failure(*keys):
    now = time.time()
    with _fail_lock:
        for k in keys:
            _failures.setdefault(k, []).append(now)


def clear_failures(*keys):
    with _fail_lock:
        for k in keys:
            _failures.pop(k, None)


# ---------------------------------------------------------------- HTTP


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def note_json(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "share_token": row["share_token"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "NoteShare"
    sys_version = ""

    # -- plumbing ---------------------------------------------------------

    def log_message(self, fmt, *args):
        # Never log the Authorization header or bodies; just the request line.
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def send_json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self.send_json(404, {"error": "Not found"})
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Invalid Content-Length")
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "Request body too large")
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            raise ApiError(400, "Request body must be JSON")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "Request body must be a JSON object")
        return data

    def current_user_id(self):
        auth = self.headers.get("Authorization", "")
        parts = auth.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
            raise ApiError(401, "Missing or invalid Authorization header")
        token = parts[1].strip()
        row = db().execute(
            "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (sha256(token),)
        ).fetchone()
        if row is None or row["expires_at"] < time.time():
            raise ApiError(401, "Invalid or expired token")
        return row["user_id"]

    def client_ip(self):
        return self.client_address[0]

    def dispatch(self, method):
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/"):
                return self.route_api(method, path)
            if method not in ("GET", "HEAD"):
                raise ApiError(405, "Method not allowed")
            return self.route_static(path)
        except ApiError as e:
            self.send_json(e.status, {"error": e.message})
        except Exception:
            import traceback

            traceback.print_exc()
            self.send_json(500, {"error": "Internal server error"})
        finally:
            close_db()

    def do_GET(self):
        self.dispatch("GET")

    def do_HEAD(self):
        self.dispatch("HEAD")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")

    # -- static pages -----------------------------------------------------

    def route_static(self, path):
        if path == "/" or path == "/index.html":
            return self.send_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        if path.startswith("/s/"):
            return self.send_file(os.path.join(STATIC_DIR, "shared.html"), "text/html; charset=utf-8")
        files = {
            "/app.js": ("app.js", "application/javascript; charset=utf-8"),
            "/shared.js": ("shared.js", "application/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        if path in files:
            name, ctype = files[path]
            return self.send_file(os.path.join(STATIC_DIR, name), ctype)
        raise ApiError(404, "Not found")

    # -- API --------------------------------------------------------------

    def route_api(self, method, path):
        parts = [p for p in path.split("/") if p][1:]  # strip "api"

        if parts == ["signup"]:
            self.require(method, "POST")
            return self.signup()
        if parts == ["login"]:
            self.require(method, "POST")
            return self.login()
        if parts == ["logout"]:
            self.require(method, "POST")
            return self.logout()
        if len(parts) == 2 and parts[0] == "shared":
            self.require(method, "GET", "HEAD")
            return self.get_shared(parts[1])

        if parts and parts[0] == "notes":
            user_id = self.current_user_id()
            if len(parts) == 1:
                if method in ("GET", "HEAD"):
                    return self.list_notes(user_id)
                if method == "POST":
                    return self.create_note(user_id)
                raise ApiError(405, "Method not allowed")
            note_id = self.parse_id(parts[1])
            if len(parts) == 2:
                if method in ("GET", "HEAD"):
                    return self.send_json(200, note_json(self.own_note(user_id, note_id)))
                if method == "PUT":
                    return self.update_note(user_id, note_id)
                if method == "DELETE":
                    return self.delete_note(user_id, note_id)
                raise ApiError(405, "Method not allowed")
            if len(parts) == 3 and parts[2] == "share":
                if method == "POST":
                    return self.share_note(user_id, note_id)
                if method == "DELETE":
                    return self.unshare_note(user_id, note_id)
                raise ApiError(405, "Method not allowed")

        raise ApiError(404, "Not found")

    @staticmethod
    def require(method, *allowed):
        if method not in allowed:
            raise ApiError(405, "Method not allowed")

    @staticmethod
    def parse_id(s):
        if not s.isdigit() or len(s) > 18:
            raise ApiError(404, "Note not found")
        return int(s)

    def own_note(self, user_id, note_id):
        row = db().execute(
            "SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id)
        ).fetchone()
        if row is None:
            # Same answer whether it doesn't exist or belongs to someone else.
            raise ApiError(404, "Note not found")
        return row

    @staticmethod
    def credentials(data):
        email = data.get("email")
        password = data.get("password")
        if not isinstance(email, str) or not isinstance(password, str):
            raise ApiError(400, "email and password are required")
        email = email.strip().lower()
        if len(email) > 254 or not EMAIL_RE.match(email):
            raise ApiError(400, "Please enter a valid email address")
        if len(password) > MAX_PASSWORD_LEN:
            raise ApiError(400, "Password is too long")
        return email, password

    @staticmethod
    def note_fields(data):
        title = data.get("title")
        body = data.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            raise ApiError(400, "title and body are required and must be strings")
        title = title.strip()
        if not title:
            raise ApiError(400, "Title cannot be empty")
        if len(title) > MAX_TITLE_LEN:
            raise ApiError(400, "Title is too long (max %d characters)" % MAX_TITLE_LEN)
        if len(body) > MAX_NOTE_LEN:
            raise ApiError(400, "Body is too long (max %d characters)" % MAX_NOTE_LEN)
        return title, body

    def signup(self):
        email, password = self.credentials(self.read_json())
        if len(password) < MIN_PASSWORD_LEN:
            raise ApiError(400, "Password must be at least %d characters" % MIN_PASSWORD_LEN)
        conn = db()
        try:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, hash_password(password), int(time.time())),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ApiError(409, "An account with that email already exists")
        self.send_json(201, {"id": cur.lastrowid, "email": email})

    def login(self):
        email, password = self.credentials(self.read_json())
        keys = ("ip:" + self.client_ip(), "email:" + email)
        if too_many_failures(*keys):
            raise ApiError(429, "Too many failed login attempts. Please wait a few minutes.")
        conn = db()
        row = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
        ok = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
        if not row or not ok:
            record_failure(*keys)
            raise ApiError(401, "Wrong email or password")
        clear_failures("email:" + email)
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (sha256(token), row["id"], now + SESSION_LIFETIME),
        )
        conn.commit()
        self.send_json(200, {"token": token})

    def logout(self):
        self.current_user_id()
        token = self.headers.get("Authorization", "").split(" ", 1)[1].strip()
        conn = db()
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (sha256(token),))
        conn.commit()
        self.send_json(200, {"ok": True})

    def list_notes(self, user_id):
        rows = db().execute(
            "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC, id DESC", (user_id,)
        ).fetchall()
        self.send_json(200, [note_json(r) for r in rows])

    def create_note(self, user_id):
        title, body = self.note_fields(self.read_json())
        now = int(time.time())
        conn = db()
        cur = conn.execute(
            "INSERT INTO notes (user_id, title, body, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, title, body, now, now),
        )
        conn.commit()
        self.send_json(201, note_json(self.own_note(user_id, cur.lastrowid)))

    def update_note(self, user_id, note_id):
        self.own_note(user_id, note_id)
        title, body = self.note_fields(self.read_json())
        conn = db()
        conn.execute(
            "UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (title, body, int(time.time()), note_id, user_id),
        )
        conn.commit()
        self.send_json(200, note_json(self.own_note(user_id, note_id)))

    def delete_note(self, user_id, note_id):
        self.own_note(user_id, note_id)
        conn = db()
        conn.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id))
        conn.commit()
        self.send_json(200, {"ok": True})

    def share_note(self, user_id, note_id):
        row = self.own_note(user_id, note_id)
        token = row["share_token"]
        if not token:
            token = secrets.token_urlsafe(24)
            conn = db()
            conn.execute(
                "UPDATE notes SET share_token = ? WHERE id = ? AND user_id = ?", (token, note_id, user_id)
            )
            conn.commit()
        self.send_json(200, {"share_token": token})

    def unshare_note(self, user_id, note_id):
        self.own_note(user_id, note_id)
        conn = db()
        conn.execute("UPDATE notes SET share_token = NULL WHERE id = ? AND user_id = ?", (note_id, user_id))
        conn.commit()
        self.send_json(200, {"ok": True})

    def get_shared(self, share_token):
        if not share_token or len(share_token) > 100:
            raise ApiError(404, "Shared note not found")
        row = db().execute(
            "SELECT title, body, updated_at FROM notes WHERE share_token = ?", (share_token,)
        ).fetchone()
        if row is None:
            raise ApiError(404, "Shared note not found")
        self.send_json(200, {"title": row["title"], "body": row["body"], "updated_at": row["updated_at"]})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128


def main():
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = Server((host, port), Handler)
    print("NoteShare running on http://localhost:%d" % port, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
