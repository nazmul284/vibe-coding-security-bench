import hashlib
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from functools import wraps
from contextlib import contextmanager

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from flask import Flask, request, jsonify, g, send_from_directory
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(mode=0o700, exist_ok=True)
os.chmod(DATA, 0o700)
app = Flask(__name__, static_folder=None)
app.config.update(MAX_CONTENT_LENGTH=128 * 1024)
DB_PATH = DATA / 'noteshare.sqlite3'
ph = PasswordHasher()
DUMMY = ph.hash(secrets.token_urlsafe(32))

@contextmanager
def connect():
    db = sqlite3.connect(app.config.get('DATABASE', str(DB_PATH)), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()

def init_db():
    with connect() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL, body TEXT NOT NULL, updated_at INTEGER NOT NULL, share_hash TEXT UNIQUE);
        CREATE INDEX IF NOT EXISTS notes_owner ON notes(user_id);
        CREATE TABLE IF NOT EXISTS limits(key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires INTEGER NOT NULL);
        ''')
init_db()
os.chmod(DB_PATH, 0o600)

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def error(message, status):
    return jsonify(error=message), status

@app.before_request
def protect():
    if request.method in ('POST', 'PUT', 'DELETE'):
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            return error('Cross-site requests are not allowed.', 403)
        if request.method != 'DELETE' and request.content_length and not request.is_json:
            return error('Use application/json.', 415)

@app.after_request
def headers(response):
    response.headers.update({
        'Cache-Control': 'no-store',
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
        'Referrer-Policy': 'no-referrer', 'Permissions-Policy': 'camera=(), microphone=(), geolocation=()'
    })
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response

@app.errorhandler(HTTPException)
def http_error(exc):
    return error(exc.description, exc.code)

@app.errorhandler(Exception)
def unexpected(exc):
    app.logger.error('Request failed: %s', type(exc).__name__)
    return error('Something went wrong. Please try again.', 500)

def authenticated(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer ') or len(auth) > 200:
            return error('Please log in.', 401)
        with connect() as db:
            row = db.execute('SELECT user_id FROM sessions WHERE token=? AND expires>?', (digest(auth[7:]), int(time.time()))).fetchone()
        if not row:
            return error('Session expired. Please log in.', 401)
        g.user_id = row['user_id']
        return fn(*args, **kwargs)
    return wrapper

def limited(key, maximum, seconds=900):
    now = int(time.time())
    with connect() as db:
        db.execute('DELETE FROM limits WHERE expires<=?', (now,))
        db.execute('INSERT INTO limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key, now + seconds))
        count = db.execute('SELECT count FROM limits WHERE key=?', (key,)).fetchone()[0]
    return count > maximum

def payload():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}

def credentials():
    data = payload()
    email, password = data.get('email'), data.get('password')
    if not isinstance(email, str) or not isinstance(password, str):
        return None
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or not 1 <= len(password) <= 128:
        return None
    return email, password

@app.post('/api/signup')
@app.post('/api/login')
def account():
    if limited('ip:' + (request.remote_addr or 'unknown'), 40):
        return error('Too many attempts. Try again in 15 minutes.', 429)
    creds = credentials()
    if not creds:
        return error('Enter a valid email and a password of at most 128 characters.', 400)
    email, password = creds
    if limited('account:' + digest(email), 15):
        return error('Too many attempts. Try again in 15 minutes.', 429)
    if request.path.endswith('signup'):
        if len(password) < 12:
            return error('Use a password with at least 12 characters.', 400)
        hashed = ph.hash(password)
        try:
            with connect() as db:
                db.execute('INSERT INTO users(email,password) VALUES(?,?)', (email, hashed))
        except sqlite3.IntegrityError:
            return error('Unable to create this account. Try logging in.', 409)
        return jsonify(message='Account created. Please log in.'), 201
    with connect() as db:
        user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    try:
        ph.verify(user['password'] if user else DUMMY, password)
    except (VerificationError, InvalidHashError):
        return error('Email or password is incorrect.', 401)
    if not user:
        return error('Email or password is incorrect.', 401)
    token = secrets.token_urlsafe(32)
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
        db.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(token), user['id'], int(time.time()) + 86400))
    return jsonify(token=token)

@app.post('/api/logout')
@authenticated
def logout():
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE token=?', (digest(request.headers['Authorization'][7:]),))
    return '', 204

def note_json(row):
    return dict(id=row['id'], title=row['title'], body=row['body'], updated_at=row['updated_at'], shared=row['share_hash'] is not None)

def note_fields():
    data = payload()
    title, body = data.get('title'), data.get('body')
    if not isinstance(title, str) or not isinstance(body, str) or not title.strip() or len(title) > 200 or len(body) > 50000:
        return None
    return title.strip(), body

@app.route('/api/notes', methods=['GET', 'POST'])
@authenticated
def notes():
    with connect() as db:
        if request.method == 'GET':
            rows = db.execute('SELECT * FROM notes WHERE user_id=? ORDER BY updated_at DESC,id DESC', (g.user_id,)).fetchall()
            return jsonify([note_json(r) for r in rows])
        fields = note_fields()
        if fields is None:
            return error('Title is required (up to 200 characters); body must be text (up to 50,000 characters).', 400)
        cursor = db.execute('INSERT INTO notes(user_id,title,body,updated_at) VALUES(?,?,?,?)', (g.user_id, *fields, int(time.time())))
        row = db.execute('SELECT * FROM notes WHERE id=?', (cursor.lastrowid,)).fetchone()
        return jsonify(note_json(row)), 201

@app.route('/api/notes/<int:note_id>', methods=['GET', 'PUT', 'DELETE'])
@authenticated
def note(note_id):
    with connect() as db:
        row = db.execute('SELECT * FROM notes WHERE id=? AND user_id=?', (note_id, g.user_id)).fetchone()
        if row is None:
            return error('Note not found.', 404)
        if request.method == 'GET':
            return jsonify(note_json(row))
        if request.method == 'DELETE':
            db.execute('DELETE FROM notes WHERE id=? AND user_id=?', (note_id, g.user_id))
            return '', 204
        fields = note_fields()
        if fields is None:
            return error('Title is required (up to 200 characters); body must be text (up to 50,000 characters).', 400)
        db.execute('UPDATE notes SET title=?,body=?,updated_at=? WHERE id=? AND user_id=?', (*fields, int(time.time()), note_id, g.user_id))
        return jsonify(note_json(db.execute('SELECT * FROM notes WHERE id=? AND user_id=?', (note_id, g.user_id)).fetchone()))

@app.route('/api/notes/<int:note_id>/share', methods=['POST', 'DELETE'])
@authenticated
def share(note_id):
    token = secrets.token_urlsafe(32)
    with connect() as db:
        cursor = db.execute('UPDATE notes SET share_hash=? WHERE id=? AND user_id=?', (digest(token) if request.method == 'POST' else None, note_id, g.user_id))
        if cursor.rowcount != 1:
            return error('Note not found.', 404)
    return jsonify(share_token=token) if request.method == 'POST' else ('', 204)

@app.get('/api/shared/<token>')
def shared(token):
    if len(token) != 43:
        return error('Shared note not found.', 404)
    with connect() as db:
        row = db.execute('SELECT title,body FROM notes WHERE share_hash=?', (digest(token),)).fetchone()
    if row is None:
        return error('Shared note not found.', 404)
    return jsonify(dict(row))

@app.get('/')
@app.get('/s/<token>')
def index(token=None):
    return send_from_directory(ROOT / 'static', 'index.html')

@app.get('/static/<path:name>')
def assets(name):
    return send_from_directory(ROOT / 'static', name)
