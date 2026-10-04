#!/usr/bin/env python3
"""NoteShare: dependency-free HTTP application with durable SQLite storage."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
SESSION_LIFETIME = 30 * 24 * 3600
MAX_REQUEST = 1024 * 1024
RATE_LOCK = threading.Lock()
RATE = {}


def connect():
    db = sqlite3.connect(DATA / 'noteshare.sqlite3', timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db


def initialize():
    DATA.mkdir(mode=0o700, exist_ok=True)
    with connect() as db:
        db.execute('PRAGMA journal_mode = WAL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, salt TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                title TEXT NOT NULL, body TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                share_hash TEXT UNIQUE
            );
            CREATE INDEX IF NOT EXISTS notes_owner ON notes(user_id);
        ''')
    os.chmod(DATA / 'noteshare.sqlite3', 0o600)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def note_json(row, public=False):
    keys = ('id', 'title', 'body', 'created_at', 'updated_at')
    note = {key: row[key] for key in keys}
    if not public:
        note['shared'] = row['share_hash'] is not None
    return note


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Handler(BaseHTTPRequestHandler):
    server_version = 'NoteShare'

    def log_message(self, fmt, *args):
        # Share links and bearer tokens must not end up in request logs.
        pass

    def respond(self, status, payload=None, mime='application/json; charset=utf-8'):
        body = b'' if payload is None else (json.dumps(payload).encode() if mime.startswith('application/json') else payload)
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def read_json(self):
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            raise ApiError(415, 'Send JSON with Content-Type: application/json.')
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise ApiError(400, 'Invalid request length.')
        if length <= 0 or length > MAX_REQUEST:
            raise ApiError(413 if length > MAX_REQUEST else 400, 'Request body is missing or too large.')
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, 'Invalid JSON.')
        if not isinstance(data, dict):
            raise ApiError(400, 'Send a JSON object.')
        return data

    def credentials(self):
        data = self.read_json()
        email, password = data.get('email'), data.get('password')
        if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email.strip()):
            raise ApiError(400, 'Enter a valid email address.')
        if not isinstance(password, str) or not 8 <= len(password) <= 256:
            raise ApiError(400, 'Password must be between 8 and 256 characters.')
        return email.strip().lower(), password

    def throttle(self):
        now = time.time()
        address = self.client_address[0]
        with RATE_LOCK:
            for key in list(RATE):
                if now - RATE[key][0] >= 60:
                    del RATE[key]
            start, count = RATE.get(address, (now, 0))
            if count >= 20:
                raise ApiError(429, 'Too many attempts. Please wait a minute.')
            RATE[address] = (start, count + 1)

    def user(self, db):
        auth = self.headers.get('Authorization', '')
        if not auth.startswith('Bearer ') or len(auth) > 256:
            raise ApiError(401, 'Please log in to continue.')
        row = db.execute('SELECT user_id FROM sessions WHERE token_hash = ? AND expires > ?', (digest(auth[7:]), int(time.time()))).fetchone()
        if row is None:
            raise ApiError(401, 'Your session has expired. Please log in again.')
        return row['user_id']

    def note_fields(self):
        data = self.read_json()
        title, body = data.get('title'), data.get('body')
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ApiError(400, 'Give your note a title of 1–200 characters.')
        if not isinstance(body, str) or len(body) > 100000:
            raise ApiError(400, 'Note body must be text, up to 100,000 characters.')
        return title.strip(), body

    def dispatch(self):
        path = urlsplit(self.path).path
        method = self.command
        if method == 'GET' and (path in ('/', '/app.js', '/style.css') or re.fullmatch(r'/shared/[A-Za-z0-9_-]+', path)):
            filename, mime = {'/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}.get(path, ('index.html', 'text/html; charset=utf-8'))
            return self.respond(200, (ROOT / 'static' / filename).read_bytes(), mime)
        if not path.startswith('/api/'):
            raise ApiError(404, 'Not found.')
        with connect() as db:
            if path in ('/api/signup', '/api/login') and method == 'POST':
                self.throttle()
                email, password = self.credentials()
                if path == '/api/signup':
                    salt = secrets.token_hex(16)
                    hashed = password_hash(password, salt)
                    try:
                        db.execute('INSERT INTO users(email,password_hash,salt) VALUES(?,?,?)', (email, hashed, salt))
                    except sqlite3.IntegrityError:
                        raise ApiError(409, 'An account with this email already exists. Please log in.')
                    db.commit()
                    return self.respond(201, {'email': email})
                row = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
                hashed = password_hash(password, row['salt'] if row else '00' * 16)
                if row is None or not hmac.compare_digest(hashed, row['password_hash']):
                    raise ApiError(401, 'Email or password is incorrect.')
                token = secrets.token_urlsafe(32)
                db.execute('DELETE FROM sessions WHERE expires <= ?', (int(time.time()),))
                db.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(token), row['id'], int(time.time()) + SESSION_LIFETIME))
                db.commit()
                return self.respond(200, {'token': token})
            shared = re.fullmatch(r'/api/shared/([^/]+)', path)
            if shared and method == 'GET':
                row = db.execute('SELECT * FROM notes WHERE share_hash = ?', (digest(shared[1]),)).fetchone()
                if row is None:
                    raise ApiError(404, 'This shared note is no longer available.')
                return self.respond(200, note_json(row, public=True))
            owner = self.user(db)
            if path == '/api/logout' and method == 'POST':
                db.execute('DELETE FROM sessions WHERE token_hash = ?', (digest(self.headers['Authorization'][7:]),))
                db.commit()
                return self.respond(204)
            if path == '/api/notes':
                if method == 'GET':
                    rows = db.execute('SELECT * FROM notes WHERE user_id = ? ORDER BY updated_at DESC, id', (owner,)).fetchall()
                    return self.respond(200, [note_json(row) for row in rows])
                if method == 'POST':
                    title, body = self.note_fields()
                    note_id = secrets.token_hex(16)
                    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                    db.execute('INSERT INTO notes(id,user_id,title,body,created_at,updated_at) VALUES(?,?,?,?,?,?)', (note_id, owner, title, body, now, now))
                    row = db.execute('SELECT * FROM notes WHERE id = ?', (note_id,)).fetchone()
                    db.commit()
                    return self.respond(201, note_json(row))
                raise ApiError(405, 'Method not allowed.')
            match = re.fullmatch(r'/api/notes/([A-Za-z0-9_-]+)(/share)?', path)
            if match:
                note_id, share = match.groups()
                row = db.execute('SELECT * FROM notes WHERE id = ? AND user_id = ?', (note_id, owner)).fetchone()
                if row is None:
                    raise ApiError(404, 'Note not found.')
                if share:
                    if method == 'POST':
                        token = secrets.token_urlsafe(32)
                        db.execute('UPDATE notes SET share_hash = ? WHERE id = ? AND user_id = ?', (digest(token), note_id, owner))
                        db.commit()
                        return self.respond(200, {'share_token': token})
                    if method == 'DELETE':
                        db.execute('UPDATE notes SET share_hash = NULL WHERE id = ? AND user_id = ?', (note_id, owner))
                        db.commit()
                        return self.respond(204)
                elif method == 'GET':
                    return self.respond(200, note_json(row))
                elif method == 'PUT':
                    title, body = self.note_fields()
                    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                    db.execute('UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ? AND user_id = ?', (title, body, now, note_id, owner))
                    row = db.execute('SELECT * FROM notes WHERE id = ?', (note_id,)).fetchone()
                    db.commit()
                    return self.respond(200, note_json(row))
                elif method == 'DELETE':
                    db.execute('DELETE FROM notes WHERE id = ? AND user_id = ?', (note_id, owner))
                    db.commit()
                    return self.respond(204)
                raise ApiError(405, 'Method not allowed.')
            raise ApiError(404, 'Not found.')

    def handle_request(self):
        self.connection.settimeout(20)
        try:
            self.dispatch()
        except ApiError as error:
            self.respond(error.status, {'error': error.message})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            import traceback
            traceback.print_exc()
            self.respond(500, {'error': 'Something went wrong. Please try again.'})

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = handle_request


if __name__ == '__main__':
    os.umask(0o077)
    initialize()
    port = int(os.environ.get('PORT', '3000'))
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    print(f'NoteShare is running at http://localhost:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
