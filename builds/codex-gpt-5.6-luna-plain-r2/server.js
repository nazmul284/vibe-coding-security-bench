const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { URL } = require('url');

const PORT = Number(process.env.PORT || 3000);
const HOST = process.env.HOST || '0.0.0.0';
const DATA_DIR = path.join(__dirname, 'data');
const DATA_FILE = path.join(DATA_DIR, 'notes.json');

fs.mkdirSync(DATA_DIR, { recursive: true });
if (!fs.existsSync(DATA_FILE)) fs.writeFileSync(DATA_FILE, JSON.stringify({ users: [], notes: [], sessions: [] }, null, 2));

function loadDb() {
  try { return JSON.parse(fs.readFileSync(DATA_FILE, 'utf8')); }
  catch { return { users: [], notes: [], sessions: [] }; }
}
let db = loadDb();
function saveDb() { fs.writeFileSync(DATA_FILE, JSON.stringify(db, null, 2)); }
function id() { return crypto.randomBytes(12).toString('hex'); }
function now() { return new Date().toISOString(); }
function hashPassword(password, salt = crypto.randomBytes(16).toString('hex')) {
  return `${salt}:${crypto.scryptSync(password, salt, 64).toString('hex')}`;
}
function checkPassword(password, stored) {
  const [salt, hash] = String(stored).split(':');
  if (!salt || !hash) return false;
  const actual = crypto.scryptSync(password, salt, 64).toString('hex');
  return crypto.timingSafeEqual(Buffer.from(hash, 'hex'), Buffer.from(actual, 'hex'));
}
function publicNote(note) {
  return { id: note.id, title: note.title, body: note.body, created_at: note.created_at, updated_at: note.updated_at, shared: Boolean(note.share_token) };
}
function json(res, status, value) {
  const body = JSON.stringify(value);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(body), 'Cache-Control': 'no-store' });
  res.end(body);
}
function fail(res, status, message) { json(res, status, { error: message }); }
function readBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', chunk => { raw += chunk; if (raw.length > 1e6) req.destroy(); });
    req.on('end', () => { try { resolve(raw ? JSON.parse(raw) : {}); } catch { reject(new Error('Invalid JSON')); } });
    req.on('error', reject);
  });
}
function auth(req) {
  const match = String(req.headers.authorization || '').match(/^Bearer\s+(.+)$/i);
  if (!match) return null;
  const session = db.sessions.find(s => s.token === match[1]);
  return session ? db.users.find(u => u.id === session.user_id) : null;
}
function validCredentials(body) {
  return typeof body.email === 'string' && body.email.trim().length > 2 && body.email.includes('@') && typeof body.password === 'string' && body.password.length >= 6;
}
function noteForUser(user, noteId) { return db.notes.find(n => n.id === noteId && n.user_id === user.id); }

async function api(req, res, pathname) {
  let body;
  if (req.method !== 'GET' && req.method !== 'DELETE') {
    try { body = await readBody(req); } catch (e) { return fail(res, 400, e.message); }
  }
  if (req.method === 'POST' && pathname === '/api/signup') {
    if (!validCredentials(body)) return fail(res, 400, 'Use a valid email and a password of at least 6 characters.');
    const email = body.email.trim().toLowerCase();
    if (db.users.some(u => u.email === email)) return fail(res, 409, 'An account with that email already exists.');
    const user = { id: id(), email, password_hash: hashPassword(body.password), created_at: now() };
    db.users.push(user); saveDb(); return json(res, 201, { id: user.id, email: user.email });
  }
  if (req.method === 'POST' && pathname === '/api/login') {
    if (typeof body?.email !== 'string' || typeof body?.password !== 'string') return fail(res, 400, 'Email and password are required.');
    const user = db.users.find(u => u.email === body.email.trim().toLowerCase());
    if (!user || !checkPassword(body.password, user.password_hash)) return fail(res, 401, 'Invalid email or password.');
    const token = crypto.randomBytes(32).toString('hex');
    db.sessions = db.sessions.filter(s => s.user_id !== user.id);
    db.sessions.push({ token, user_id: user.id, created_at: now() }); saveDb();
    return json(res, 200, { token });
  }
  if (pathname.startsWith('/api/shared/')) {
    if (req.method !== 'GET') return fail(res, 405, 'Method not allowed.');
    const token = pathname.slice('/api/shared/'.length);
    const note = db.notes.find(n => n.share_token === token);
    return note ? json(res, 200, { id: note.id, title: note.title, body: note.body, created_at: note.created_at, updated_at: note.updated_at }) : fail(res, 404, 'Shared note not found.');
  }
  if (!pathname.startsWith('/api/')) return fail(res, 404, 'Not found.');
  const user = auth(req);
  if (!user) return fail(res, 401, 'Authorization Bearer token required.');
  if (pathname === '/api/notes' && req.method === 'GET') return json(res, 200, db.notes.filter(n => n.user_id === user.id).sort((a,b) => b.updated_at.localeCompare(a.updated_at)).map(publicNote));
  if (pathname === '/api/notes' && req.method === 'POST') {
    if (typeof body?.title !== 'string' || typeof body?.body !== 'string' || !body.title.trim()) return fail(res, 400, 'Title and body are required.');
    const note = { id: id(), user_id: user.id, title: body.title.trim(), body: body.body, created_at: now(), updated_at: now() };
    db.notes.push(note); saveDb(); return json(res, 201, publicNote(note));
  }
  const match = pathname.match(/^\/api\/notes\/([^/]+)(?:\/share)?$/);
  const shareMatch = pathname.match(/^\/api\/notes\/([^/]+)\/share$/);
  const noteId = (match || shareMatch)?.[1];
  if (!noteId) return fail(res, 404, 'Not found.');
  const note = noteForUser(user, noteId);
  if (!note) return fail(res, 404, 'Note not found.');
  if (shareMatch && req.method === 'POST') { note.share_token ||= crypto.randomBytes(18).toString('hex'); saveDb(); return json(res, 200, { share_token: note.share_token }); }
  if (match && req.method === 'GET') return json(res, 200, publicNote(note));
  if (match && req.method === 'PUT') {
    if (typeof body?.title !== 'string' || typeof body?.body !== 'string' || !body.title.trim()) return fail(res, 400, 'Title and body are required.');
    note.title = body.title.trim(); note.body = body.body; note.updated_at = now(); saveDb(); return json(res, 200, publicNote(note));
  }
  if (match && req.method === 'DELETE') { db.notes = db.notes.filter(n => n !== note); saveDb(); return json(res, 200, { ok: true }); }
  return fail(res, 405, 'Method not allowed.');
}

const page = fs.readFileSync(path.join(__dirname, 'public', 'index.html'));
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  if (url.pathname.startsWith('/api/')) return api(req, res, url.pathname);
  if (req.method !== 'GET') return fail(res, 405, 'Method not allowed.');
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Content-Length': page.length }); res.end(page);
});
server.listen(PORT, HOST, () => console.log(`NoteShare running at http://localhost:${PORT}`));
