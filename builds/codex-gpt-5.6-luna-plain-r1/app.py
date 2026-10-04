#!/usr/bin/env python3
import hashlib
import html
import json
import os
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "noteshare.db"
STATIC_PATH = ROOT / "index.html"
PORT = int(os.environ.get("PORT", "8000"))


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
        CREATE TABLE IF NOT EXISTS shares (
            share_token TEXT PRIMARY KEY,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id);
        """)


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + ":" + digest.hex()


def password_ok(password, stored):
    try:
        salt, expected = stored.split(":", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_note(row):
    return {"id": row["id"], "title": row["title"], "body": row["body"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


class App(BaseHTTPRequestHandler):
    server_version = "NoteShare/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, payload, status=200):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def error(self, message, status=400):
        self.send_json({"error": message}, status)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 1_000_000:
                raise ValueError
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            raise ValueError("Request body must be valid JSON")

    def user_id(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        with db() as conn:
            row = conn.execute("SELECT user_id FROM sessions WHERE token_hash = ?", (token_hash(auth[7:].strip()),)).fetchone()
        return row["user_id"] if row else None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            data = STATIC_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path.startswith("/shared/"):
            share = path.rsplit("/", 1)[-1]
            with db() as conn:
                row = conn.execute("SELECT n.* FROM notes n JOIN shares s ON s.note_id=n.id WHERE s.share_token=?", (share,)).fetchone()
            if not row:
                return self.error("Shared note not found", 404)
            title = html.escape(row["title"])
            body = html.escape(row["body"])
            html_data = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · NoteShare</title><style>body{{margin:0;background:#f7f6f1;color:#19342f;font:16px/1.65 system-ui,sans-serif}}main{{max-width:680px;margin:12vh auto;padding:0 24px}}.brand{{color:#207a60;font-weight:800;letter-spacing:-.5px;margin-bottom:55px}}article{{background:#fffefa;border:1px solid #e2e8e2;border-radius:20px;padding:32px;box-shadow:0 12px 35px #204b3e0d}}h1{{font-size:32px;letter-spacing:-1px;margin:0 0 24px}}.body{{white-space:pre-wrap;color:#536963}}</style><main><div class="brand">NoteShare</div><article><h1>{title}</h1><div class="body">{body}</div></article></main></html>'''.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_data)))
            self.end_headers()
            self.wfile.write(html_data)
            return
        if path.startswith("/api/shared/"):
            share = path.rsplit("/", 1)[-1]
            with db() as conn:
                row = conn.execute("SELECT n.* FROM notes n JOIN shares s ON s.note_id=n.id WHERE s.share_token=?", (share,)).fetchone()
            if not row:
                return self.error("Shared note not found", 404)
            return self.send_json(public_note(row))
        uid = self.user_id()
        if not uid:
            return self.error("Authentication required", 401)
        if path == "/api/notes":
            with db() as conn:
                rows = conn.execute("SELECT * FROM notes WHERE user_id=? ORDER BY updated_at DESC, id DESC", (uid,)).fetchall()
            return self.send_json([public_note(row) for row in rows])
        note_id = self.note_id(path)
        if note_id is not None:
            with db() as conn:
                row = conn.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (note_id, uid)).fetchone()
            if not row:
                return self.error("Note not found", 404)
            return self.send_json(public_note(row))
        self.error("Not found", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
        except ValueError as exc:
            return self.error(str(exc))
        if path == "/api/signup":
            email, password = str(payload.get("email", "")).strip().lower(), payload.get("password", "")
            if "@" not in email or len(email) < 5:
                return self.error("Please enter a valid email")
            if not isinstance(password, str) or len(password) < 8:
                return self.error("Password must be at least 8 characters")
            try:
                with db() as conn:
                    conn.execute("INSERT INTO users(email,password_hash) VALUES(?,?)", (email, password_hash(password)))
            except sqlite3.IntegrityError:
                return self.error("An account with that email already exists", 409)
            return self.send_json({"message": "Account created"}, 201)
        if path == "/api/login":
            email, password = str(payload.get("email", "")).strip().lower(), payload.get("password", "")
            with db() as conn:
                user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
                if not user or not password_ok(password, user["password_hash"]):
                    return self.error("Invalid email or password", 401)
                token = secrets.token_urlsafe(32)
                conn.execute("INSERT INTO sessions(token_hash,user_id) VALUES(?,?)", (token_hash(token), user["id"]))
            return self.send_json({"token": token})
        uid = self.user_id()
        if not uid:
            return self.error("Authentication required", 401)
        if path == "/api/notes":
            title, body = str(payload.get("title", "")).strip(), str(payload.get("body", ""))
            if not title:
                return self.error("Title is required")
            with db() as conn:
                cur = conn.execute("INSERT INTO notes(user_id,title,body) VALUES(?,?,?)", (uid, title, body))
                row = conn.execute("SELECT * FROM notes WHERE id=?", (cur.lastrowid,)).fetchone()
            return self.send_json(public_note(row), 201)
        note_id = self.note_id(path[:-6].rstrip("/")) if path.endswith("/share") else None
        if note_id is not None:
            note_id = self.note_id(path[:-6].rstrip("/"))
            with db() as conn:
                if not conn.execute("SELECT 1 FROM notes WHERE id=? AND user_id=?", (note_id, uid)).fetchone():
                    return self.error("Note not found", 404)
                share = secrets.token_urlsafe(24)
                conn.execute("INSERT INTO shares(share_token,note_id) VALUES(?,?)", (share, note_id))
            return self.send_json({"share_token": share})
        self.error("Not found", 404)

    def do_PUT(self):
        path = urlparse(self.path).path
        uid = self.user_id()
        if not uid:
            return self.error("Authentication required", 401)
        note_id = self.note_id(path)
        if note_id is None:
            return self.error("Not found", 404)
        try:
            payload = self.read_json()
        except ValueError as exc:
            return self.error(str(exc))
        title, body = str(payload.get("title", "")).strip(), str(payload.get("body", ""))
        if not title:
            return self.error("Title is required")
        with db() as conn:
            cur = conn.execute("UPDATE notes SET title=?, body=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?", (title, body, note_id, uid))
            if not cur.rowcount:
                return self.error("Note not found", 404)
            row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        self.send_json(public_note(row))

    def do_DELETE(self):
        path = urlparse(self.path).path
        uid = self.user_id()
        if not uid:
            return self.error("Authentication required", 401)
        note_id = self.note_id(path)
        if note_id is None:
            return self.error("Not found", 404)
        with db() as conn:
            cur = conn.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, uid))
        if not cur.rowcount:
            return self.error("Note not found", 404)
        self.send_json({"message": "Note deleted"})

    @staticmethod
    def note_id(path):
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "notes"] and parts[2].isdigit():
            return int(parts[2])
        return None


if __name__ == "__main__":
    init_db()
    print(f"NoteShare running at http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), App).serve_forever()
