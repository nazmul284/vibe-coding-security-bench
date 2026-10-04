#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "noteshare.db"
MAX_BODY = 1_100_000
MAX_TITLE = 200
MAX_NOTE = 1_000_000
TOKEN_TTL = 30 * 24 * 60 * 60
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
NOTE_RE = re.compile(r"^/api/notes/(\d+)$")
SHARE_RE = re.compile(r"^/api/notes/(\d+)/share$")
SHARED_RE = re.compile(r"^/api/shared/([A-Za-z0-9_-]{20,200})$")

rate_lock = threading.Lock()
rate_attempts = {}


def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
          password_hash TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
          expires_at INTEGER NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
        CREATE TABLE IF NOT EXISTS notes (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT NOT NULL,
          body TEXT NOT NULL, share_hash TEXT UNIQUE, created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS notes_owner ON notes(user_id, updated_at DESC);
        """)


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def password_ok(password, stored):
    try:
        kind, n, r, p, salt, expected = stored.split("$")
        if kind != "scrypt": return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def note_json(row):
    return {"id": row["id"], "title": row["title"], "body": row["body"],
            "shared": bool(row["share_hash"]), "created_at": row["created_at"], "updated_at": row["updated_at"]}


class Handler(BaseHTTPRequestHandler):
    server_version = "NoteShare"
    sys_version = ""

    def log_message(self, fmt, *args):
        print(f'{self.address_string()} - {fmt % args}', flush=True)

    def log_request(self, code="-", size="-"):
        # Query strings can contain share tokens, so never place them in logs.
        safe_path = urlparse(self.path).path
        self.log_message('"%s %s" %s %s', self.command, safe_path, str(code), str(size))

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def file(self, name, content_type):
        data = (ROOT / "static" / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        raw_len = self.headers.get("Content-Length")
        if not raw_len: raise ValueError("JSON body required")
        try: length = int(raw_len)
        except ValueError: raise ValueError("Invalid Content-Length")
        if length < 0 or length > MAX_BODY: raise ValueError("Request body too large")
        if "application/json" not in self.headers.get("Content-Type", "").lower():
            raise ValueError("Content-Type must be application/json")
        try: value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError): raise ValueError("Invalid JSON")
        if not isinstance(value, dict): raise ValueError("JSON body must be an object")
        return value

    def auth(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "): return None
        token = header[7:]
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", token): return None
        now = int(time.time())
        with db() as con:
            row = con.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?", (token_hash(token), now)).fetchone()
            if secrets.randbelow(100) == 0: con.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
        return row["user_id"] if row else None

    def require_auth(self):
        uid = self.auth()
        if not uid: self.json(401, {"error": "Authentication required"})
        return uid

    def rate_limited(self):
        key = self.client_address[0]
        now = time.monotonic()
        with rate_lock:
            hits = [t for t in rate_attempts.get(key, []) if now - t < 60]
            if len(hits) >= 12: return True
            hits.append(now); rate_attempts[key] = hits
        return False

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/": return self.file("index.html", "text/html; charset=utf-8")
        if path == "/app.js": return self.file("app.js", "application/javascript; charset=utf-8")
        if path == "/style.css": return self.file("style.css", "text/css; charset=utf-8")
        if path == "/api/notes":
            uid = self.require_auth()
            if not uid: return
            with db() as con: rows = con.execute("SELECT * FROM notes WHERE user_id=? ORDER BY updated_at DESC", (uid,)).fetchall()
            return self.json(200, [note_json(r) for r in rows])
        match = NOTE_RE.match(path)
        if match:
            uid = self.require_auth()
            if not uid: return
            with db() as con: row = con.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (match.group(1), uid)).fetchone()
            return self.json(200, note_json(row)) if row else self.json(404, {"error": "Note not found"})
        match = SHARED_RE.match(path)
        if match:
            with db() as con: row = con.execute("SELECT * FROM notes WHERE share_hash=?", (token_hash(match.group(1)),)).fetchone()
            if not row: return self.json(404, {"error": "Shared note not found"})
            return self.json(200, {"title": row["title"], "body": row["body"], "updated_at": row["updated_at"]})
        self.json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try: data = self.body()
        except ValueError as e: return self.json(400, {"error": str(e)})
        if path == "/api/signup":
            if self.rate_limited(): return self.json(429, {"error": "Too many attempts; try again shortly"})
            email, password = data.get("email"), data.get("password")
            if not isinstance(email, str) or not EMAIL_RE.fullmatch(email.strip()) or len(email) > 254:
                return self.json(400, {"error": "Enter a valid email address"})
            if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
                return self.json(400, {"error": "Password must be 12–1024 characters"})
            try:
                with db() as con: con.execute("INSERT INTO users(email,password_hash,created_at) VALUES(?,?,?)", (email.strip().lower(), password_hash(password), int(time.time())))
            except sqlite3.IntegrityError: return self.json(409, {"error": "An account with that email already exists"})
            return self.json(201, {"message": "Account created"})
        if path == "/api/login":
            if self.rate_limited(): return self.json(429, {"error": "Too many attempts; try again shortly"})
            email, password = data.get("email"), data.get("password")
            if not isinstance(email, str) or not isinstance(password, str): return self.json(400, {"error": "Email and password required"})
            with db() as con: row = con.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
            if not row or not password_ok(password, row["password_hash"]): return self.json(401, {"error": "Invalid email or password"})
            token = secrets.token_urlsafe(32); now = int(time.time())
            with db() as con: con.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), row["id"], now + TOKEN_TTL))
            return self.json(200, {"token": token})
        if path == "/api/notes":
            uid = self.require_auth()
            if not uid: return
            valid = self.validate_note(data)
            if isinstance(valid, str): return self.json(400, {"error": valid})
            title, body = valid; now = int(time.time())
            with db() as con:
                cur = con.execute("INSERT INTO notes(user_id,title,body,created_at,updated_at) VALUES(?,?,?,?,?)", (uid,title,body,now,now))
                row = con.execute("SELECT * FROM notes WHERE id=?", (cur.lastrowid,)).fetchone()
            return self.json(201, note_json(row))
        match = SHARE_RE.match(path)
        if match:
            uid = self.require_auth()
            if not uid: return
            token = secrets.token_urlsafe(32)
            with db() as con:
                cur = con.execute("UPDATE notes SET share_hash=? WHERE id=? AND user_id=?", (token_hash(token), match.group(1), uid))
            if not cur.rowcount: return self.json(404, {"error": "Note not found"})
            return self.json(200, {"share_token": token})
        self.json(404, {"error": "Not found"})

    def validate_note(self, data):
        title, body = data.get("title"), data.get("body")
        if not isinstance(title, str) or not title.strip(): return "Title is required"
        if not isinstance(body, str): return "Body must be text"
        if len(title) > MAX_TITLE: return f"Title cannot exceed {MAX_TITLE} characters"
        if len(body) > MAX_NOTE: return f"Body cannot exceed {MAX_NOTE} characters"
        return title.strip(), body

    def do_PUT(self):
        path = urlparse(self.path).path; match = NOTE_RE.match(path)
        if not match: return self.json(404, {"error": "Not found"})
        try: data = self.body()
        except ValueError as e: return self.json(400, {"error": str(e)})
        uid = self.require_auth()
        if not uid: return
        valid = self.validate_note(data)
        if isinstance(valid, str): return self.json(400, {"error": valid})
        with db() as con:
            cur = con.execute("UPDATE notes SET title=?,body=?,updated_at=? WHERE id=? AND user_id=?", (*valid,int(time.time()),match.group(1),uid))
            row = con.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (match.group(1),uid)).fetchone()
        return self.json(200, note_json(row)) if cur.rowcount else self.json(404, {"error": "Note not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path; match = NOTE_RE.match(path)
        if not match: return self.json(404, {"error": "Not found"})
        uid = self.require_auth()
        if not uid: return
        with db() as con: cur = con.execute("DELETE FROM notes WHERE id=? AND user_id=?", (match.group(1),uid))
        return self.json(200, {"message": "Note deleted"}) if cur.rowcount else self.json(404, {"error": "Note not found"})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    print(f"NoteShare listening on http://0.0.0.0:{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
