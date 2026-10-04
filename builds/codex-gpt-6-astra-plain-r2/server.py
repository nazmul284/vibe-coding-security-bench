#!/usr/bin/env python3
"""NoteShare: standard-library HTTP server and persistent SQLite storage."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('NOTESHARE_DATA_DIR', str(ROOT / 'data')))
DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
DB = DATA / 'noteshare.sqlite3'
SESSION_AGE = 30 * 24 * 60 * 60


def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


with connect() as db:
    db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL,
          salt TEXT NOT NULL, password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS notes (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
          title TEXT NOT NULL, body TEXT NOT NULL,
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
          share_token TEXT UNIQUE);
        CREATE INDEX IF NOT EXISTS notes_owner ON notes(user_id);
    ''')
os.chmod(DB, 0o600)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def note_json(row, public=False):
    fields = ('id', 'title', 'body', 'created_at', 'updated_at')
    result = {key: row[key] for key in fields}
    if not public:
        result['share_token'] = row['share_token']
    return result


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Handler(BaseHTTPRequestHandler):
    server_version = 'NoteShare'

    def log_message(self, fmt, *args):
        # Do not write bearer tokens or private share URLs to logs.
        pass

    def respond(self, status, payload=None, content_type='application/json; charset=utf-8'):
        body = (json.dumps(payload).encode() if content_type.startswith('application/json')
                else payload or b'')
        if status == 204:
            body = b''
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            raise APIError(415, 'Send a JSON body with Content-Type: application/json.')
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise APIError(400, 'Invalid content length.')
        if length < 0 or length > 1_000_000:
            raise APIError(413, 'Request is too large.')
        try:
            value = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            raise APIError(400, 'Invalid JSON.')
        if not isinstance(value, dict):
            raise APIError(400, 'Send a JSON object.')
        return value

    def user(self, db):
        auth = self.headers.get('Authorization', '')
        if not auth.startswith('Bearer ') or len(auth) > 512:
            raise APIError(401, 'Please log in.')
        row = db.execute('SELECT user_id FROM sessions WHERE token_hash=? AND expires>?',
                         (digest(auth[7:]), int(time.time()))).fetchone()
        if not row:
            raise APIError(401, 'Your session has expired. Please log in again.')
        return row['user_id']

    def handle_request(self):
        self.connection.settimeout(15)
        try:
            self.route()
        except APIError as error:
            self.respond(error.status, {'error': error.message})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.respond(500, {'error': 'Something went wrong. Please try again.'})

    def route(self):
        path = urlsplit(self.path).path
        method = self.command
        if not path.startswith('/api/'):
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8')}
            entry = files.get(path)
            if re.fullmatch(r'/shared/[A-Za-z0-9_-]+', path):
                entry = files['/']
            if method != 'GET' or not entry:
                raise APIError(404, 'Page not found.')
            return self.respond(200, (ROOT / 'static' / entry[0]).read_bytes(), entry[1])
        with connect() as db:
            if path in ('/api/signup', '/api/login') and method == 'POST':
                value = self.read_json()
                email, password = value.get('email'), value.get('password')
                if not isinstance(email, str) or not isinstance(password, str):
                    raise APIError(400, 'Email and password are required.')
                email = email.strip().lower()
                if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
                    raise APIError(400, 'Enter a valid email address.')
                if not 8 <= len(password) <= 1024:
                    raise APIError(400, 'Your password must contain 8–1024 characters.')
                if path == '/api/signup':
                    salt = secrets.token_hex(16)
                    hashed = password_hash(password, salt)
                    try:
                        cursor = db.execute('INSERT INTO users(email,salt,password_hash) VALUES(?,?,?)', (email, salt, hashed))
                    except sqlite3.IntegrityError:
                        raise APIError(409, 'An account with this email already exists.')
                    db.commit()
                    return self.respond(201, {'id': cursor.lastrowid, 'email': email})
                row = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
                calculated = password_hash(password, row['salt'] if row else '00' * 16)
                if not row or not hmac.compare_digest(calculated, row['password_hash']):
                    raise APIError(401, 'Incorrect email or password.')
                token = secrets.token_urlsafe(32)
                db.execute('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
                db.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(token), row['id'], int(time.time()) + SESSION_AGE))
                db.commit()
                return self.respond(200, {'token': token})
            shared = re.fullmatch(r'/api/shared/([A-Za-z0-9_-]+)', path)
            if shared and method == 'GET':
                row = db.execute('SELECT * FROM notes WHERE share_token=?', (shared[1],)).fetchone()
                if not row:
                    raise APIError(404, 'This shared note is unavailable.')
                return self.respond(200, note_json(row, public=True))
            owner = self.user(db)
            if path == '/api/logout' and method == 'POST':
                db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(self.headers['Authorization'][7:]),))
                db.commit()
                return self.respond(204)
            if path == '/api/notes' and method == 'GET':
                rows = db.execute('SELECT * FROM notes WHERE user_id=? ORDER BY updated_at DESC, id DESC', (owner,)).fetchall()
                return self.respond(200, [note_json(row) for row in rows])
            match = re.fullmatch(r'/api/notes/([0-9]+)(/share)?', path)
            row = None
            if match:
                row = db.execute('SELECT * FROM notes WHERE id=? AND user_id=?', (match[1], owner)).fetchone()
                if not row:
                    raise APIError(404, 'Note not found.')
                if match[2]:
                    if method not in ('POST', 'DELETE'):
                        raise APIError(405, 'Method not allowed.')
                    token = (row['share_token'] or secrets.token_urlsafe(32)) if method == 'POST' else None
                    db.execute('UPDATE notes SET share_token=? WHERE id=?', (token, row['id']))
                    db.commit()
                    return self.respond(200, {'share_token': token})
                if method == 'GET':
                    return self.respond(200, note_json(row))
                if method == 'DELETE':
                    db.execute('DELETE FROM notes WHERE id=?', (row['id'],))
                    db.commit()
                    return self.respond(204)
            if (path == '/api/notes' and method == 'POST') or (match and method == 'PUT'):
                value = self.read_json()
                title, body = value.get('title'), value.get('body')
                if not isinstance(title, str) or not title.strip() or len(title) > 200:
                    raise APIError(400, 'Enter a title between 1 and 200 characters.')
                if not isinstance(body, str) or len(body) > 200_000:
                    raise APIError(400, 'Body must be text, up to 200,000 characters.')
                now = int(time.time())
                if row:
                    note_id = row['id']
                    db.execute('UPDATE notes SET title=?,body=?,updated_at=? WHERE id=? AND user_id=?', (title.strip(), body, now, note_id, owner))
                else:
                    note_id = db.execute('INSERT INTO notes(user_id,title,body,created_at,updated_at) VALUES(?,?,?,?,?)', (owner, title.strip(), body, now, now)).lastrowid
                db.commit()
                result = db.execute('SELECT * FROM notes WHERE id=?', (note_id,)).fetchone()
                return self.respond(200 if row else 201, note_json(result))
            raise APIError(405 if path == '/api/notes' or match else 404, 'Endpoint or method not available.')

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = handle_request


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '3000'))
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    print(f'NoteShare is running at http://localhost:{port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
