#!/usr/bin/env python3
"""NoteShare: a small, dependency-free notes web app and JSON API."""

import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "noteshare.db"
STATIC_DIR = ROOT / "static"
MAX_BODY = 1_000_000
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
NOTE_PATH_RE = re.compile(r"^/api/notes/(\d+)$")
SHARE_PATH_RE = re.compile(r"^/api/notes/(\d+)/share$")
PUBLIC_SHARE_RE = re.compile(r"^/api/shared/([A-Za-z0-9_-]+)$")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def password_matches(password, encoded):
    try:
        algorithm, rounds, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected_hex))
    except (ValueError, TypeError):
        return False


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    DATA_DIR.mkdir(exist_ok=True)
    with connect() as db:
        db.executescript(
            """
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                share_token_hash TEXT UNIQUE,
                share_token TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS notes_user_id ON notes(user_id);
            CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
            """
        )


def note_json(row, include_share=True):
    result = {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_share:
        result["share_token"] = row["share_token"]
    return result


class App(BaseHTTPRequestHandler):
    server_version = "NoteShare/1.0"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid Content-Length")
        if length <= 0 or length > MAX_BODY:
            raise ValueError("Request body is missing or too large")
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise ValueError("Content-Type must be application/json")
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("Invalid JSON")
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def current_user(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header[7:].strip()
        if not token:
            return None
        with connect() as db:
            return db.execute(
                "SELECT users.id, users.email FROM sessions "
                "JOIN users ON users.id = sessions.user_id WHERE sessions.token_hash = ?",
                (token_hash(token),),
            ).fetchone()

    def require_user(self):
        user = self.current_user()
        if not user:
            self.send_json(401, {"error": "Authentication required"})
        return user

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/notes":
            return self.list_notes()
        match = NOTE_PATH_RE.match(path)
        if match:
            return self.get_note(int(match.group(1)))
        match = PUBLIC_SHARE_RE.match(path)
        if match:
            return self.get_shared(match.group(1))
        if path.startswith("/api/"):
            return self.send_json(404, {"error": "Not found"})
        return self.serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/signup":
            return self.signup()
        if path == "/api/login":
            return self.login()
        if path == "/api/notes":
            return self.create_note()
        match = SHARE_PATH_RE.match(path)
        if match:
            return self.share_note(int(match.group(1)))
        self.send_json(404, {"error": "Not found"})

    def do_PUT(self):
        match = NOTE_PATH_RE.match(urlparse(self.path).path)
        if match:
            return self.update_note(int(match.group(1)))
        self.send_json(404, {"error": "Not found"})

    def do_DELETE(self):
        match = NOTE_PATH_RE.match(urlparse(self.path).path)
        if match:
            return self.delete_note(int(match.group(1)))
        self.send_json(404, {"error": "Not found"})

    def signup(self):
        try:
            data = self.read_json()
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password", "")
        if len(email) > 254 or not EMAIL_RE.match(email):
            return self.send_json(400, {"error": "Enter a valid email address"})
        if not isinstance(password, str) or len(password) < 8:
            return self.send_json(400, {"error": "Password must be at least 8 characters"})
        if len(password) > 1024:
            return self.send_json(400, {"error": "Password is too long"})
        try:
            with connect() as db:
                cursor = db.execute(
                    "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
                    (email, password_hash(password), utc_now()),
                )
            self.send_json(201, {"id": cursor.lastrowid, "email": email})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "An account with that email already exists"})

    def login(self):
        try:
            data = self.read_json()
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password", "")
        if not isinstance(password, str):
            password = ""
        with connect() as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if not user or not password_matches(password, user["password_hash"]):
                return self.send_json(401, {"error": "Invalid email or password"})
            token = secrets.token_urlsafe(32)
            db.execute(
                "INSERT INTO sessions(token_hash, user_id, created_at) VALUES (?, ?, ?)",
                (token_hash(token), user["id"], utc_now()),
            )
        self.send_json(200, {"token": token})

    def note_fields(self):
        data = self.read_json()
        title, body = data.get("title"), data.get("body")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Title is required")
        if not isinstance(body, str):
            raise ValueError("Body must be text")
        title = title.strip()
        if len(title) > 200:
            raise ValueError("Title must be 200 characters or fewer")
        if len(body) > 100_000:
            raise ValueError("Body must be 100,000 characters or fewer")
        return title, body

    def list_notes(self):
        user = self.require_user()
        if not user:
            return
        with connect() as db:
            rows = db.execute(
                "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
                (user["id"],),
            ).fetchall()
        self.send_json(200, [note_json(row) for row in rows])

    def create_note(self):
        user = self.require_user()
        if not user:
            return
        try:
            title, body = self.note_fields()
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        now = utc_now()
        with connect() as db:
            cursor = db.execute(
                "INSERT INTO notes(user_id, title, body, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user["id"], title, body, now, now),
            )
            row = db.execute("SELECT * FROM notes WHERE id = ?", (cursor.lastrowid,)).fetchone()
        self.send_json(201, note_json(row))

    def owned_note(self, note_id, user_id):
        with connect() as db:
            return db.execute(
                "SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id)
            ).fetchone()

    def get_note(self, note_id):
        user = self.require_user()
        if not user:
            return
        row = self.owned_note(note_id, user["id"])
        if not row:
            return self.send_json(404, {"error": "Note not found"})
        self.send_json(200, note_json(row))

    def update_note(self, note_id):
        user = self.require_user()
        if not user:
            return
        try:
            title, body = self.note_fields()
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        with connect() as db:
            cursor = db.execute(
                "UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (title, body, utc_now(), note_id, user["id"]),
            )
            if cursor.rowcount == 0:
                return self.send_json(404, {"error": "Note not found"})
            row = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        self.send_json(200, note_json(row))

    def delete_note(self, note_id):
        user = self.require_user()
        if not user:
            return
        with connect() as db:
            cursor = db.execute(
                "DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, user["id"])
            )
        if cursor.rowcount == 0:
            return self.send_json(404, {"error": "Note not found"})
        self.send_json(200, {"deleted": True})

    def share_note(self, note_id):
        user = self.require_user()
        if not user:
            return
        with connect() as db:
            row = db.execute(
                "SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, user["id"])
            ).fetchone()
            if not row:
                return self.send_json(404, {"error": "Note not found"})
            share_token = row["share_token"]
            if not share_token:
                share_token = secrets.token_urlsafe(24)
                db.execute(
                    "UPDATE notes SET share_token = ?, share_token_hash = ? WHERE id = ?",
                    (share_token, token_hash(share_token), note_id),
                )
        self.send_json(200, {"share_token": share_token})

    def get_shared(self, share_token):
        with connect() as db:
            row = db.execute(
                "SELECT * FROM notes WHERE share_token_hash = ?", (token_hash(share_token),)
            ).fetchone()
        if not row:
            return self.send_json(404, {"error": "Shared note not found"})
        self.send_json(200, note_json(row, include_share=False))

    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        relative = Path(unquote(path).lstrip("/"))
        if ".." in relative.parts:
            return self.send_error(404)
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents or not target.is_file():
            return self.send_error(404)
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    init_db()
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError:
        raise SystemExit("PORT must be a number")
    server = ThreadingHTTPServer(("0.0.0.0", port), App)
    print(f"NoteShare is running at http://localhost:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
