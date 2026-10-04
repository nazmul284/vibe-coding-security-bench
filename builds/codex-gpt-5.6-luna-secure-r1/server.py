#!/usr/bin/env python3
"""NoteShare: a small, dependency-free notes app and JSON API."""
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
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "noteshare.sqlite3"
STATIC_DIR = ROOT / "static"
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "")
MAX_BODY = 256 * 1024
EMAIL_RE = re.compile(r"^[^@\s]{1,128}@[^@\s]{1,255}\.[^@\s]{2,63}$")

DB_LOCK = threading.RLock()
LIMIT_LOCK = threading.Lock()
ATTEMPTS = {}


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    DATA_DIR.mkdir(mode=0o700, exist_ok=True)
    with DB_LOCK, db() as conn:
        conn.executescript("""
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS shares (
            share_hash TEXT PRIMARY KEY,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS notes_user_idx ON notes(user_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS shares_note_idx ON shares(note_id);
        """)
    try:
        os.chmod(DATA_DIR, 0o700)
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def password_hash(password):
    salt = secrets.token_bytes(16)
    # scrypt is provided by Python/OpenSSL and is deliberately expensive.
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$16384$8$1$%s$%s" % (salt.hex(), digest.hex())


def password_ok(password, encoded):
    try:
        kind, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if kind != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def limited(key, window=60, max_attempts=12):
    now = time.monotonic()
    with LIMIT_LOCK:
        old = [t for t in ATTEMPTS.get(key, []) if now - t < window]
        if len(old) >= max_attempts:
            ATTEMPTS[key] = old
            return False
        old.append(now)
        ATTEMPTS[key] = old
        return True


def note_json(row):
    return {"id": row["id"], "title": row["title"], "body": row["body"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


class Handler(BaseHTTPRequestHandler):
    server_version = "NoteShare/1.0"

    def log_message(self, fmt, *args):
        # Keep logs useful but never log request bodies, tokens, or note contents.
        super().log_message(fmt, *args)

    def headers_common(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        if CORS_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
            self.send_header("Vary", "Origin")

    def reply(self, status, payload, content_type="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.headers_common()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def error(self, status, message):
        self.reply(status, {"error": message})

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError
            raw = self.rfile.read(length)
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, json.JSONDecodeError):
            self.error(HTTPStatus.BAD_REQUEST, "Request body must be a JSON object")
            return None

    def auth_user(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer ") or len(header) > 300:
            return None
        token = header[7:].strip()
        if not token:
            return None
        with DB_LOCK, db() as conn:
            row = conn.execute("SELECT user_id FROM sessions WHERE token_hash = ?", (token_hash(token),)).fetchone()
        return row["user_id"] if row else None

    def do_OPTIONS(self):
        if CORS_ORIGIN:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.headers_common()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
        else:
            self.error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/":
            try:
                body = (STATIC_DIR / "index.html").read_bytes()
                self.reply(HTTPStatus.OK, body, "text/html; charset=utf-8")
            except OSError:
                self.error(500, "App is not configured")
            return
        if re.fullmatch(r"/shared/[A-Za-z0-9_-]{32,128}", path):
            try:
                body = (STATIC_DIR / "shared.html").read_bytes()
                self.reply(HTTPStatus.OK, body, "text/html; charset=utf-8")
            except OSError:
                self.error(500, "App is not configured")
            return
        if path.startswith("/api/shared/"):
            share = path.split("/", 3)[3]
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", share):
                self.error(404, "Shared note not found")
                return
            with DB_LOCK, db() as conn:
                row = conn.execute("SELECT n.* FROM shares s JOIN notes n ON n.id=s.note_id WHERE s.share_hash=?", (token_hash(share),)).fetchone()
            if not row:
                self.error(404, "Shared note not found")
            else:
                self.reply(200, note_json(row))
            return
        if path == "/api/notes":
            user_id = self.auth_user()
            if not user_id:
                self.error(401, "Authentication required")
                return
            with DB_LOCK, db() as conn:
                rows = conn.execute("SELECT * FROM notes WHERE user_id=? ORDER BY updated_at DESC, id DESC", (user_id,)).fetchall()
            self.reply(200, [note_json(row) for row in rows])
            return
        match = re.fullmatch(r"/api/notes/(\d+)", path)
        if match:
            user_id = self.auth_user()
            if not user_id:
                self.error(401, "Authentication required")
                return
            with DB_LOCK, db() as conn:
                row = conn.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (int(match.group(1)), user_id)).fetchone()
            if not row:
                self.error(404, "Note not found")
            else:
                self.reply(200, note_json(row))
            return
        self.error(404, "Not found")

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        ip = self.client_address[0]
        if path in ("/api/signup", "/api/login") and not limited(ip + ":auth"):
            self.error(429, "Too many attempts; try again later")
            return
        # Share creation has no required request body.
        if re.fullmatch(r"/api/notes/(\d+)/share", path):
            data = {}
        else:
            data = self.read_json()
            if data is None:
                return
        if path == "/api/signup":
            email = data.get("email", "")
            password = data.get("password", "")
            if not isinstance(email, str) or not EMAIL_RE.fullmatch(email) or not isinstance(password, str) or not 12 <= len(password) <= 200:
                self.error(400, "Use a valid email and a password 12–200 characters long")
                return
            with DB_LOCK, db() as conn:
                try:
                    conn.execute("INSERT INTO users(email,password_hash) VALUES(?,?)", (email.strip().lower(), password_hash(password)))
                except sqlite3.IntegrityError:
                    self.error(409, "An account with that email already exists")
                    return
            self.reply(201, {"message": "Account created"})
            return
        if path == "/api/login":
            email = data.get("email", "")
            password = data.get("password", "")
            with DB_LOCK, db() as conn:
                row = conn.execute("SELECT * FROM users WHERE email=?", (str(email).strip().lower(),)).fetchone()
            if not row or not isinstance(password, str) or not password_ok(password, row["password_hash"]):
                self.error(401, "Invalid email or password")
                return
            token = secrets.token_urlsafe(32)
            with DB_LOCK, db() as conn:
                conn.execute("INSERT INTO sessions(token_hash,user_id) VALUES(?,?)", (token_hash(token), row["id"]))
            self.reply(200, {"token": token})
            return
        user_id = self.auth_user()
        if not user_id:
            self.error(401, "Authentication required")
            return
        if path == "/api/notes":
            title, body = data.get("title"), data.get("body")
            if not isinstance(title, str) or not isinstance(body, str) or not title.strip() or len(title) > 300 or len(body) > 100000:
                self.error(400, "Title is required and must be at most 300 characters; body must be at most 100,000 characters")
                return
            with DB_LOCK, db() as conn:
                cur = conn.execute("INSERT INTO notes(user_id,title,body) VALUES(?,?,?)", (user_id, title.strip(), body))
                row = conn.execute("SELECT * FROM notes WHERE id=?", (cur.lastrowid,)).fetchone()
            self.reply(201, note_json(row))
            return
        match = re.fullmatch(r"/api/notes/(\d+)/share", path)
        if match:
            with DB_LOCK, db() as conn:
                row = conn.execute("SELECT id FROM notes WHERE id=? AND user_id=?", (int(match.group(1)), user_id)).fetchone()
                if not row:
                    self.error(404, "Note not found")
                    return
                share = secrets.token_urlsafe(32)
                conn.execute("INSERT INTO shares(share_hash,note_id) VALUES(?,?)", (token_hash(share), row["id"]))
            self.reply(201, {"share_token": share, "share_url": "/shared/" + share})
            return
        self.error(404, "Not found")

    def do_PUT(self):
        path = urlparse(self.path).path.rstrip("/")
        user_id = self.auth_user()
        if not user_id:
            self.error(401, "Authentication required")
            return
        match = re.fullmatch(r"/api/notes/(\d+)", path)
        if not match:
            self.error(404, "Not found")
            return
        data = self.read_json()
        if data is None:
            return
        title, body = data.get("title"), data.get("body")
        if not isinstance(title, str) or not isinstance(body, str) or not title.strip() or len(title) > 300 or len(body) > 100000:
            self.error(400, "Title is required and must be at most 300 characters; body must be at most 100,000 characters")
            return
        with DB_LOCK, db() as conn:
            cur = conn.execute("UPDATE notes SET title=?,body=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?", (title.strip(), body, int(match.group(1)), user_id))
            row = conn.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (int(match.group(1)), user_id)).fetchone()
        if cur.rowcount == 0:
            self.error(404, "Note not found")
        else:
            self.reply(200, note_json(row))

    def do_DELETE(self):
        path = urlparse(self.path).path.rstrip("/")
        user_id = self.auth_user()
        if not user_id:
            self.error(401, "Authentication required")
            return
        match = re.fullmatch(r"/api/notes/(\d+)", path)
        if not match:
            self.error(404, "Not found")
            return
        with DB_LOCK, db() as conn:
            cur = conn.execute("DELETE FROM notes WHERE id=? AND user_id=?", (int(match.group(1)), user_id))
        if cur.rowcount == 0:
            self.error(404, "Note not found")
        else:
            self.reply(204, b"")


if __name__ == "__main__":
    init_db()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"NoteShare listening on http://{HOST}:{PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
