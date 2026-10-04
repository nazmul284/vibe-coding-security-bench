#!/usr/bin/env python3
import base64, hashlib, hmac, html, json, os, re, secrets, sqlite3, threading, time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "noteshare.sqlite3")
PORT = int(os.environ.get("PORT", "8000"))
MAX_BODY = 256 * 1024
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
db_lock = threading.RLock()
rate_lock = threading.Lock()
rate = {}

def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notes (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          title TEXT NOT NULL, body TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS shares (
          id INTEGER PRIMARY KEY, note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
          token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS notes_user_idx ON notes(user_id);
        CREATE INDEX IF NOT EXISTS shares_token_idx ON shares(token_hash);
        """)

def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def password_hash(password):
    salt = secrets.token_bytes(16)
    # scrypt is provided by Python/OpenSSL and is deliberately expensive.
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**13, r=8, p=1)
    return "scrypt$8192$8$1$" + b64(salt) + "$" + b64(digest)

def password_ok(password, encoded):
    try:
        kind, n, r, p, salt, digest = encoded.split("$")
        if kind != "scrypt": return False
        got = hashlib.scrypt(password.encode(), salt=base64.urlsafe_b64decode(salt + "=="), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(got, base64.urlsafe_b64decode(digest + "=="))
    except (ValueError, TypeError):
        return False

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()

def note_json(row):
    return {"id": row["id"], "title": row["title"], "body": row["body"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

class Handler(BaseHTTPRequestHandler):
    server_version = "NoteShare/1.0"

    def log_message(self, fmt, *args):
        # Avoid logging credentials, request bodies, or tokens.
        super().log_message(fmt, *args)

    def send_json(self, status, obj, extra=None):
        data = json_bytes(obj)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.security_headers()
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(data)

    def security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY: raise ValueError()
            return json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            raise ValueError("Invalid or oversized JSON body")

    def client_key(self): return self.client_address[0]

    def limited(self):
        now = time.time(); key = self.client_key()
        with rate_lock:
            values = [t for t in rate.get(key, []) if t > now - 60]
            values.append(now); rate[key] = values
            return len(values) > 120

    def auth_user(self, allow_cookie=True):
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        cookie = self.headers.get("Cookie", "")
        if not token and allow_cookie:
            for part in cookie.split(";"):
                k, _, v = part.strip().partition("=")
                if k == "noteshare_session": token = v; break
        if not token or len(token) > 200: return None
        try:
            uid = int(token.split(".", 1)[0])
            sig = token.split(".", 1)[1]
            expected = b64(hmac.new(self.server.session_secret, token.split(".", 1)[0].encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(sig, expected): return None
            with db() as c: return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        except (ValueError, IndexError): return None

    def make_token(self, uid):
        part = str(uid); sig = b64(hmac.new(self.server.session_secret, part.encode(), hashlib.sha256).digest())
        return part + "." + sig

    def require_user(self):
        user = self.auth_user()
        if not user: self.send_json(401, {"error": "Authentication required"})
        return user

    def origin_ok(self):
        # Browser cookie mutations must come from this origin; bearer API calls may omit Origin.
        origin = self.headers.get("Origin")
        return not origin or origin in ("http://localhost:%d" % PORT, "http://127.0.0.1:%d" % PORT)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/": return self.page()
        if path.startswith("/api/shared/"):
            token = path.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[A-Za-z0-9_-]{30,200}", token): return self.send_json(404, {"error": "Shared note not found"})
            with db() as c: row = c.execute("SELECT n.* FROM notes n JOIN shares s ON s.note_id=n.id WHERE s.token_hash=?", (token_hash(token),)).fetchone()
            return self.send_json(200, note_json(row)) if row else self.send_json(404, {"error": "Shared note not found"})
        if not path.startswith("/api/"): return self.send_json(404, {"error": "Not found"})
        user = self.require_user()
        if not user: return
        if path == "/api/notes":
            with db() as c: rows = c.execute("SELECT * FROM notes WHERE user_id=? ORDER BY updated_at DESC, id DESC", (user["id"],)).fetchall()
            return self.send_json(200, [note_json(r) for r in rows])
        m = re.fullmatch(r"/api/notes/(\d+)", path)
        if m:
            with db() as c: row = c.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (int(m.group(1)), user["id"])).fetchone()
            return self.send_json(200, note_json(row)) if row else self.send_json(404, {"error": "Note not found"})
        return self.send_json(404, {"error": "Not found"})

    def do_POST(self): self.mutate("POST")
    def do_PUT(self): self.mutate("PUT")
    def do_DELETE(self): self.mutate("DELETE")

    def mutate(self, method):
        if self.limited(): return self.send_json(429, {"error": "Too many requests"}, {"Retry-After": "60"})
        path = urlparse(self.path).path
        if path == "/api/signup" and method == "POST": return self.signup()
        if path == "/api/login" and method == "POST": return self.login()
        if not path.startswith("/api/"): return self.send_json(404, {"error": "Not found"})
        if not self.origin_ok(): return self.send_json(403, {"error": "Untrusted request origin"})
        user = self.require_user()
        if not user: return
        try: data = self.read_json() if method != "DELETE" else {}
        except ValueError as e: return self.send_json(400, {"error": str(e)})
        if path == "/api/notes" and method == "POST":
            if not isinstance(data, dict): return self.send_json(400, {"error": "JSON object required"})
            title, body = data.get("title"), data.get("body")
            if not isinstance(title, str) or not isinstance(body, str) or not title.strip() or len(title) > 200 or len(body) > 100000: return self.send_json(400, {"error": "Title and body are required; title max 200 and body max 100000 characters"})
            with db() as c:
                cur = c.execute("INSERT INTO notes(user_id,title,body) VALUES(?,?,?)", (user["id"], title.strip(), body)); row = c.execute("SELECT * FROM notes WHERE id=?", (cur.lastrowid,)).fetchone()
            return self.send_json(201, note_json(row))
        m = re.fullmatch(r"/api/notes/(\d+)(/share)?", path)
        if not m: return self.send_json(404, {"error": "Not found"})
        nid = int(m.group(1)); share = bool(m.group(2))
        with db() as c: owned = c.execute("SELECT id FROM notes WHERE id=? AND user_id=?", (nid, user["id"])).fetchone()
        if not owned: return self.send_json(404, {"error": "Note not found"})
        if share and method == "POST":
            raw = b64(secrets.token_bytes(32))
            with db() as c: c.execute("INSERT INTO shares(note_id,token_hash) VALUES(?,?)", (nid, token_hash(raw)))
            return self.send_json(201, {"share_token": raw})
        if share: return self.send_json(405, {"error": "Method not allowed"})
        if method == "DELETE":
            with db() as c: c.execute("DELETE FROM notes WHERE id=? AND user_id=?", (nid, user["id"]))
            self.send_response(204); self.security_headers(); self.end_headers(); return
        if method == "PUT":
            title, body = (data.get("title"), data.get("body")) if isinstance(data, dict) else (None, None)
            if not isinstance(title, str) or not isinstance(body, str) or not title.strip() or len(title) > 200 or len(body) > 100000: return self.send_json(400, {"error": "Invalid title or body"})
            with db() as c:
                c.execute("UPDATE notes SET title=?, body=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?", (title.strip(), body, nid, user["id"])); row = c.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
            return self.send_json(200, note_json(row))
        return self.send_json(405, {"error": "Method not allowed"})

    def signup(self):
        try: data = self.read_json()
        except ValueError as e: return self.send_json(400, {"error": str(e)})
        email, password = data.get("email", ""), data.get("password", "")
        if not isinstance(email, str) or not EMAIL_RE.fullmatch(email) or len(email) > 254 or not isinstance(password, str) or len(password) < 10 or len(password) > 200: return self.send_json(400, {"error": "Use a valid email and a password of 10–200 characters"})
        try:
            with db() as c: cur = c.execute("INSERT INTO users(email,password_hash) VALUES(?,?)", (email.strip().lower(), password_hash(password))); uid = cur.lastrowid
        except sqlite3.IntegrityError: return self.send_json(409, {"error": "An account with that email already exists"})
        return self.send_json(201, {"token": self.make_token(uid)}, {"Set-Cookie": "noteshare_session=%s; HttpOnly; SameSite=Strict; Path=/" % self.make_token(uid)})

    def login(self):
        try: data = self.read_json()
        except ValueError as e: return self.send_json(400, {"error": str(e)})
        email, password = data.get("email", ""), data.get("password", "")
        with db() as c: user = c.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone() if isinstance(email, str) else None
        if not user or not isinstance(password, str) or not password_ok(password, user["password_hash"]): return self.send_json(401, {"error": "Invalid email or password"})
        token = self.make_token(user["id"])
        return self.send_json(200, {"token": token}, {"Set-Cookie": "noteshare_session=%s; HttpOnly; SameSite=Strict; Path=/" % token})

    def page(self):
        data = PAGE.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.security_headers(); self.end_headers(); self.wfile.write(data)

PAGE = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NoteShare</title><style>
:root{font:16px system-ui,sans-serif;color:#19202a;background:#f4f6f8}body{max-width:900px;margin:0 auto;padding:24px}header{display:flex;justify-content:space-between;align-items:center}h1{color:#3157d5}main{background:white;border-radius:12px;padding:24px;box-shadow:0 2px 15px #0001}input,textarea,button{font:inherit;padding:10px;border:1px solid #ccd2dc;border-radius:7px;box-sizing:border-box}input,textarea{width:100%;margin:5px 0 12px}textarea{min-height:180px}button{background:#3157d5;color:#fff;border:0;cursor:pointer;margin:4px 4px 4px 0}.danger{background:#b52b38}.muted{color:#687386}.note{border:1px solid #e2e6ec;border-radius:8px;padding:14px;margin:10px 0}.note h3{margin:0 0 5px}.hidden{display:none}.error{color:#b52b38}.share{word-break:break-all;background:#eef2ff;padding:8px}
</style></head><body><header><h1>NoteShare</h1><button id="logout" class="hidden">Log out</button></header><main><section id="auth"><h2>Welcome</h2><p class="muted">Private notes, shareable when you choose.</p><form id="login"><h3>Log in</h3><input name="email" type="email" placeholder="Email" required><input name="password" type="password" placeholder="Password" required><button>Log in</button></form><form id="signup"><h3>Create account</h3><input name="email" type="email" placeholder="Email" required><input name="password" type="password" minlength="10" placeholder="Password (10+ characters)" required><button>Sign up</button></form><p id="authmsg" class="error"></p></section><section id="app" class="hidden"><h2>Your notes</h2><form id="editor"><input name="title" placeholder="Title" maxlength="200" required><textarea name="body" placeholder="Write your note..." maxlength="100000" required></textarea><button>Save note</button><button type="button" id="cancel">Cancel</button><input type="hidden" name="id"></form><p id="msg" class="error"></p><div id="notes"></div></section></main><script>
const $=x=>document.querySelector(x), api=async (u,o={})=>{let r=await fetch(u,{...o,headers:{'Content-Type':'application/json',...(o.headers||{})}});let j=r.status===204?{}:await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j};
function showApp(){ $('#auth').classList.add('hidden');$('#app').classList.remove('hidden');$('#logout').classList.remove('hidden');load() } function showAuth(){ $('#auth').classList.remove('hidden');$('#app').classList.add('hidden');$('#logout').classList.add('hidden') }
async function load(){let ns=await api('/api/notes');$('#notes').innerHTML=ns.map(n=>`<article class="note"><h3>${esc(n.title)}</h3><p>${esc(n.body).replace(/\n/g,'<br>')}</p><button onclick="edit(${n.id})">Edit</button><button onclick="share(${n.id})">Share</button><button class="danger" onclick="del(${n.id})">Delete</button></article>`).join('')||'<p class="muted">No notes yet.</p>'}
const esc=s=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
$('#login').onsubmit=async e=>{e.preventDefault();try{let f=new FormData(e.target);await api('/api/login',{method:'POST',body:JSON.stringify(Object.fromEntries(f))});showApp()}catch(x){$('#authmsg').textContent=x.message}};
$('#signup').onsubmit=async e=>{e.preventDefault();try{let f=new FormData(e.target);await api('/api/signup',{method:'POST',body:JSON.stringify(Object.fromEntries(f))});showApp()}catch(x){$('#authmsg').textContent=x.message}};
$('#editor').onsubmit=async e=>{e.preventDefault();let f=new FormData(e.target), id=f.get('id');try{await api(id?'/api/notes/'+id:'/api/notes',{method:id?'PUT':'POST',body:JSON.stringify({title:f.get('title'),body:f.get('body')})});e.target.reset();load()}catch(x){$('#msg').textContent=x.message}};
$('#cancel').onclick=()=>$('#editor').reset();$('#logout').onclick=()=>{document.cookie='noteshare_session=; Max-Age=0; Path=/';showAuth()};
async function edit(id){let n=await api('/api/notes/'+id),f=$('#editor');f.id.value=n.id;f.title.value=n.title;f.body.value=n.body;scrollTo(0,0)} async function del(id){if(confirm('Delete this note?')){await api('/api/notes/'+id,{method:'DELETE'});load()}} async function share(id){try{let x=await api('/api/notes/'+id+'/share',{method:'POST'});let url=location.origin+'/api/shared/'+x.share_token;prompt('Copy this read-only link:',url)}catch(x){alert(x.message)}}
</script></body></html>'''

class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    def __init__(self, addr, handler):
        super().__init__(addr, handler); self.session_secret = secrets.token_bytes(32)

if __name__ == '__main__':
    init_db(); print('NoteShare listening on http://127.0.0.1:%d' % PORT, flush=True); Server(('0.0.0.0', PORT), Handler).serve_forever()
