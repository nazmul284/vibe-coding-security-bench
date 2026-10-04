import hashlib
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from functools import wraps
from contextlib import closing

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = Path(__file__).resolve().parent
os.umask(0o077)
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def create_app(database=None):
    app = Flask(__name__, static_folder='static')
    app.config.update(MAX_CONTENT_LENGTH=128 * 1024)
    if os.environ.get('TRUSTED_HOSTS'):
        app.config['TRUSTED_HOSTS'] = os.environ['TRUSTED_HOSTS'].split(',')
    db_path = Path(database) if database else ROOT / 'data' / 'noteshare.sqlite3'
    db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL, body TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            share_hash TEXT UNIQUE);
        CREATE INDEX IF NOT EXISTS notes_owner ON notes(user_id);
        CREATE TABLE IF NOT EXISTS limits (key TEXT PRIMARY KEY, start INTEGER NOT NULL, count INTEGER NOT NULL);
        ''')
    os.chmod(db_path, 0o600)

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(db_path, timeout=10)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @app.teardown_appcontext
    def close_db(error):
        if 'db' in g:
            g.db.close()

    def fail(message, status):
        return jsonify(error=message), status

    def rate_limit(key, maximum, window):
        now = int(time.time())
        conn = db()
        with conn:
            conn.execute('DELETE FROM limits WHERE start < ?', (now - 86400,))
            conn.execute('''INSERT INTO limits VALUES (?, ?, 1) ON CONFLICT(key) DO UPDATE SET
                count=CASE WHEN start <= ? THEN 1 ELSE count+1 END,
                start=CASE WHEN start <= ? THEN excluded.start ELSE start END''',
                (key, now, now-window, now-window))
            row = conn.execute('SELECT count FROM limits WHERE key=?', (key,)).fetchone()
        return row['count'] <= maximum

    @app.before_request
    def guard():
        if request.path.startswith('/api/'):
            if not rate_limit('ip:' + (request.remote_addr or 'unknown'), 600, 60):
                return fail('Too many requests. Please try again later.', 429)
            # No cookie authentication or CORS: browsers must explicitly send a bearer token.
            if request.method in ('POST', 'PUT', 'DELETE') and request.headers.get('Sec-Fetch-Site') == 'cross-site':
                return fail('Cross-site requests are not allowed.', 403)

    @app.after_request
    def headers(response):
        response.headers.update({
            'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
            'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store',
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=()'})
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if response.status_code == 429:
            response.headers['Retry-After'] = '900'
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return fail(error.description, error.code)

    @app.errorhandler(Exception)
    def unexpected(error):
        # Do not log request bodies, credentials or secret-bearing URLs.
        app.logger.error('Internal error: %s', type(error).__name__)
        return fail('An internal error occurred.', 500)

    def payload():
        value = request.get_json()
        if not isinstance(value, dict):
            from werkzeug.exceptions import BadRequest
            raise BadRequest('Expected a JSON object.')
        return value

    def auth(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            header = request.headers.get('Authorization', '')
            parts = header.split()
            if len(parts) != 2 or parts[0].lower() != 'bearer' or len(parts[1]) > 256:
                return fail('Please log in.', 401)
            g.token_hash = digest(parts[1])
            row = db().execute('SELECT user_id FROM sessions WHERE token_hash=? AND expires>?',
                               (g.token_hash, int(time.time()))).fetchone()
            if row is None:
                return fail('Session expired or invalid. Please log in.', 401)
            g.user_id = row['user_id']
            return fn(*args, **kwargs)
        return wrapped

    def serialize(row, shared=False):
        fields = ('id', 'title', 'body', 'created_at', 'updated_at')
        result = {key: row[key] for key in fields}
        if not shared:
            result['is_shared'] = row['share_hash'] is not None
        return result

    def owned(note_id):
        return db().execute('SELECT * FROM notes WHERE id=? AND user_id=?', (note_id, g.user_id)).fetchone()

    @app.post('/api/signup')
    @app.post('/api/login')
    def credentials():
        if not rate_limit('auth-ip:' + (request.remote_addr or 'unknown'), 30, 900):
            return fail('Too many attempts. Try again in 15 minutes.', 429)
        data = payload()
        email, password = data.get('email'), data.get('password')
        if not isinstance(email, str) or not isinstance(password, str):
            return fail('Email and password must be strings.', 400)
        email = email.strip().lower()
        if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            return fail('Enter a valid email address.', 400)
        if len(password) > 128:
            return fail('Password must be at most 128 characters.', 400)
        if not rate_limit('account:' + digest(email), 15, 900):
            return fail('Too many attempts. Try again in 15 minutes.', 429)
        if request.path.endswith('signup'):
            if len(password) < 12:
                return fail('Use a password with at least 12 characters.', 400)
            hashed = generate_password_hash(password, method='scrypt')
            try:
                with db():
                    db().execute('INSERT INTO users(email,password) VALUES (?,?)', (email, hashed))
            except sqlite3.IntegrityError:
                return fail('Unable to create account with these details.', 409)
            return jsonify(message='Account created. Please log in.'), 201
        row = db().execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        valid = check_password_hash(row['password'] if row else DUMMY_HASH, password)
        if not row or not valid:
            return fail('Invalid email or password.', 401)
        token = secrets.token_urlsafe(32)
        with db():
            db().execute('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
            db().execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), row['id'], int(time.time())+86400))
        return jsonify(token=token)

    @app.post('/api/logout')
    @auth
    def logout():
        with db():
            db().execute('DELETE FROM sessions WHERE token_hash=?', (g.token_hash,))
        return '', 204

    def note_fields():
        data = payload()
        title, body = data.get('title'), data.get('body')
        if not isinstance(title, str) or not isinstance(body, str):
            return None
        if not title.strip() or len(title) > 200 or len(body) > 50000:
            return None
        return title.strip(), body

    @app.route('/api/notes', methods=['GET', 'POST'])
    @auth
    def notes():
        if request.method == 'GET':
            rows = db().execute('SELECT * FROM notes WHERE user_id=? ORDER BY updated_at DESC, id', (g.user_id,)).fetchall()
            return jsonify([serialize(row) for row in rows])
        fields = note_fields()
        if fields is None:
            return fail('Use a title of 1–200 characters and a body of up to 50,000 characters.', 400)
        note_id, now = secrets.token_urlsafe(16), int(time.time())
        with db():
            db().execute('INSERT INTO notes VALUES (?,?,?,?,?,?,NULL)', (note_id, g.user_id, *fields, now, now))
        return jsonify(serialize(owned(note_id))), 201

    @app.route('/api/notes/<note_id>', methods=['GET', 'PUT', 'DELETE'])
    @auth
    def note(note_id):
        row = owned(note_id)
        if row is None:
            return fail('Note not found.', 404)
        if request.method == 'GET':
            return jsonify(serialize(row))
        if request.method == 'DELETE':
            with db():
                db().execute('DELETE FROM notes WHERE id=? AND user_id=?', (note_id, g.user_id))
            return '', 204
        fields = note_fields()
        if fields is None:
            return fail('Use a title of 1–200 characters and a body of up to 50,000 characters.', 400)
        with db():
            db().execute('UPDATE notes SET title=?, body=?, updated_at=? WHERE id=? AND user_id=?', (*fields, int(time.time()), note_id, g.user_id))
        return jsonify(serialize(owned(note_id)))

    @app.route('/api/notes/<note_id>/share', methods=['POST', 'DELETE'])
    @auth
    def share(note_id):
        if owned(note_id) is None:
            return fail('Note not found.', 404)
        token = secrets.token_urlsafe(32) if request.method == 'POST' else None
        with db():
            db().execute('UPDATE notes SET share_hash=? WHERE id=? AND user_id=?', (digest(token) if token else None, note_id, g.user_id))
        return jsonify(share_token=token) if token else ('', 204)

    @app.get('/api/shared/<token>')
    def shared(token):
        row = db().execute('SELECT * FROM notes WHERE share_hash=?', (digest(token),)).fetchone()
        if row is None:
            return fail('This share link is unavailable.', 404)
        return jsonify(serialize(row, shared=True))

    @app.get('/')
    @app.get('/share')
    def index():
        return send_from_directory(app.static_folder, 'index.html')

    return app


if __name__ == '__main__':
    from waitress import serve
    port = int(os.environ.get('PORT', '3000'))
    print(f'NoteShare is ready at http://localhost:{port}', flush=True)
    serve(create_app(), host=os.environ.get('HOST', '0.0.0.0'), port=port,
          threads=4, max_request_body_size=128 * 1024, ident='NoteShare')
