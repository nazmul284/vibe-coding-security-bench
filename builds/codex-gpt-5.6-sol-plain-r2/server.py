#!/usr/bin/env python3
"""NoteShare: a small dependency-free notes web app and JSON API."""

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
STATIC = ROOT / "static"
DATA = ROOT / "data"
DB_PATH = DATA / "noteshare.db"
MAX_BODY = 2 * 1024 * 1024
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def init_db():
    DATA.mkdir(exist_ok=True)
    with db() as connection:
        connection.executescript(
            """
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
                share_token TEXT UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_notes_share ON notes(share_token);
            """
        )


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        algorithm, rounds, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(rounds)
        ).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_note(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "shared": bool(row["share_token"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class NoteShareHandler(BaseHTTPRequestHandler):
    server_version = "NoteShare/1.0"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, status, payload):
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def error_json(self, status, message):
        self.send_json(status, {"error": message})

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid Content-Length")
        if length <= 0:
            raise ValueError("A JSON body is required")
        if length > MAX_BODY:
            raise OverflowError("Request body is too large")
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("Invalid JSON")
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def user_id(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header[7:].strip()
        if not token:
            return None
        with db() as connection:
            row = connection.execute(
                "SELECT user_id FROM sessions WHERE token_hash = ?", (token_hash(token),)
            ).fetchone()
        return row["user_id"] if row else None

    def require_user(self):
        user_id = self.user_id()
        if user_id is None:
            self.error_json(401, "Authentication required")
        return user_id

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/notes":
            return self.list_notes()
        match = re.fullmatch(r"/api/notes/(\d+)", path)
        if match:
            return self.get_note(int(match.group(1)))
        match = re.fullmatch(r"/api/shared/([A-Za-z0-9_-]+)", path)
        if match:
            return self.get_shared(match.group(1))
        if path == "/" or path == "/index.html" or re.fullmatch(r"/share/[A-Za-z0-9_-]+", path):
            return self.serve_file(STATIC / "index.html")
        if path == "/app.js":
            return self.serve_file(STATIC / "app.js")
        if path == "/style.css":
            return self.serve_file(STATIC / "style.css")
        self.error_json(404, "Not found")

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/signup":
            return self.signup()
        if path == "/api/login":
            return self.login()
        if path == "/api/notes":
            return self.create_note()
        match = re.fullmatch(r"/api/notes/(\d+)/share", path)
        if match:
            return self.share_note(int(match.group(1)))
        self.error_json(404, "Not found")

    def do_PUT(self):
        path = unquote(urlparse(self.path).path)
        match = re.fullmatch(r"/api/notes/(\d+)", path)
        if match:
            return self.update_note(int(match.group(1)))
        self.error_json(404, "Not found")

    def do_DELETE(self):
        path = unquote(urlparse(self.path).path)
        match = re.fullmatch(r"/api/notes/(\d+)", path)
        if match:
            return self.delete_note(int(match.group(1)))
        self.error_json(404, "Not found")

    def serve_file(self, path):
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return self.error_json(404, "Not found")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(content)

    def signup(self):
        try:
            data = self.read_json()
            email = data.get("email", "").strip().lower()
            password = data.get("password", "")
            if not EMAIL_RE.fullmatch(email) or len(email) > 254:
                return self.error_json(400, "Enter a valid email address")
            if not isinstance(password, str) or len(password) < 8:
                return self.error_json(400, "Password must be at least 8 characters")
            if len(password) > 1024:
                return self.error_json(400, "Password is too long")
            with db() as connection:
                connection.execute(
                    "INSERT INTO users(email, password_hash, created_at) VALUES (?, ?, ?)",
                    (email, hash_password(password), now()),
                )
            self.send_json(201, {"message": "Account created"})
        except sqlite3.IntegrityError:
            self.error_json(409, "An account with that email already exists")
        except OverflowError as error:
            self.error_json(413, str(error))
        except ValueError as error:
            self.error_json(400, str(error))

    def login(self):
        try:
            data = self.read_json()
            email = data.get("email", "").strip().lower()
            password = data.get("password", "")
            with db() as connection:
                user = connection.execute(
                    "SELECT id, password_hash FROM users WHERE email = ?", (email,)
                ).fetchone()
                if not user or not isinstance(password, str) or not check_password(password, user["password_hash"]):
                    return self.error_json(401, "Invalid email or password")
                token = secrets.token_urlsafe(32)
                connection.execute(
                    "INSERT INTO sessions(token_hash, user_id, created_at) VALUES (?, ?, ?)",
                    (token_hash(token), user["id"], now()),
                )
            self.send_json(200, {"token": token})
        except OverflowError as error:
            self.error_json(413, str(error))
        except ValueError as error:
            self.error_json(400, str(error))

    def validated_note(self):
        data = self.read_json()
        title, body = data.get("title"), data.get("body")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Title is required")
        if not isinstance(body, str):
            raise ValueError("Body must be text")
        title = title.strip()
        if len(title) > 200:
            raise ValueError("Title must be 200 characters or fewer")
        if len(body) > 1_000_000:
            raise ValueError("Body is too long")
        return title, body

    def list_notes(self):
        user_id = self.require_user()
        if user_id is None:
            return
        with db() as connection:
            rows = connection.execute(
                "SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
                (user_id,),
            ).fetchall()
        self.send_json(200, [public_note(row) for row in rows])

    def create_note(self):
        user_id = self.require_user()
        if user_id is None:
            return
        try:
            title, body = self.validated_note()
            timestamp = now()
            with db() as connection:
                cursor = connection.execute(
                    "INSERT INTO notes(user_id, title, body, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, title, body, timestamp, timestamp),
                )
                row = connection.execute("SELECT * FROM notes WHERE id = ?", (cursor.lastrowid,)).fetchone()
            self.send_json(201, public_note(row))
        except OverflowError as error:
            self.error_json(413, str(error))
        except ValueError as error:
            self.error_json(400, str(error))

    def owned_note(self, connection, note_id, user_id):
        return connection.execute(
            "SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id)
        ).fetchone()

    def get_note(self, note_id):
        user_id = self.require_user()
        if user_id is None:
            return
        with db() as connection:
            row = self.owned_note(connection, note_id, user_id)
        if not row:
            return self.error_json(404, "Note not found")
        self.send_json(200, public_note(row))

    def update_note(self, note_id):
        user_id = self.require_user()
        if user_id is None:
            return
        try:
            title, body = self.validated_note()
            with db() as connection:
                if not self.owned_note(connection, note_id, user_id):
                    return self.error_json(404, "Note not found")
                connection.execute(
                    "UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                    (title, body, now(), note_id, user_id),
                )
                row = self.owned_note(connection, note_id, user_id)
            self.send_json(200, public_note(row))
        except OverflowError as error:
            self.error_json(413, str(error))
        except ValueError as error:
            self.error_json(400, str(error))

    def delete_note(self, note_id):
        user_id = self.require_user()
        if user_id is None:
            return
        with db() as connection:
            cursor = connection.execute(
                "DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id)
            )
        if not cursor.rowcount:
            return self.error_json(404, "Note not found")
        self.send_response(204)
        self.end_headers()

    def share_note(self, note_id):
        user_id = self.require_user()
        if user_id is None:
            return
        with db() as connection:
            row = self.owned_note(connection, note_id, user_id)
            if not row:
                return self.error_json(404, "Note not found")
            share_token = row["share_token"] or secrets.token_urlsafe(24)
            if not row["share_token"]:
                connection.execute(
                    "UPDATE notes SET share_token = ? WHERE id = ?", (share_token, note_id)
                )
        self.send_json(200, {"share_token": share_token})

    def get_shared(self, share_token):
        with db() as connection:
            row = connection.execute(
                "SELECT * FROM notes WHERE share_token = ?", (share_token,)
            ).fetchone()
        if not row:
            return self.error_json(404, "Shared note not found")
        self.send_json(200, {
            "id": row["id"], "title": row["title"], "body": row["body"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]
        })


if __name__ == "__main__":
    init_db()
    try:
        port = int(os.environ.get("PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise SystemExit("PORT must be a number from 1 to 65535")
    server = ThreadingHTTPServer(("0.0.0.0", port), NoteShareHandler)
    print(f"NoteShare is running at http://localhost:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping NoteShare.")
    finally:
        server.server_close()
