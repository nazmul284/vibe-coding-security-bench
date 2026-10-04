const app = document.getElementById('app');
const logoutBtn = document.getElementById('logout');
let token = localStorage.getItem('token');

function el(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === 'onclick' || k === 'onsubmit') e[k] = v;
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const kid of kids) e.append(kid);   // strings become text, never HTML
  return e;
}
function show(...nodes) { app.replaceChildren(...nodes); }

async function api(method, path, body) {
  const headers = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (r.status === 401 && token && !path.startsWith('/api/login')) { logout(true); throw new Error('Please log in again'); }
  if (!r.ok) throw new Error(data.error || 'Something went wrong');
  return data;
}

function logout(silent) {
  if (!silent && token) api('POST', '/api/logout').catch(() => {});
  token = null; localStorage.removeItem('token');
  route();
}
logoutBtn.onclick = () => logout();

function authView() {
  logoutBtn.hidden = true;
  const msg = el('div', { class: 'err' });
  const email = el('input', { type: 'email', placeholder: 'Email', autocomplete: 'username', required: '' });
  const pw = el('input', { type: 'password', placeholder: 'Password (8+ characters)', autocomplete: 'current-password', required: '' });
  async function go(kind) {
    msg.textContent = '';
    try {
      if (kind === 'signup') await api('POST', '/api/signup', { email: email.value, password: pw.value });
      const d = await api('POST', '/api/login', { email: email.value, password: pw.value });
      token = d.token; localStorage.setItem('token', token); route();
    } catch (e) { msg.textContent = e.message; }
  }
  show(el('div', { class: 'card' },
    el('h2', {}, 'Welcome'),
    el('form', { onsubmit: ev => { ev.preventDefault(); go('login'); } },
      email, pw, msg,
      el('button', { type: 'submit' }, 'Log in'),
      el('button', { type: 'button', class: 'secondary', onclick: () => go('signup') }, 'Sign up'))));
}

async function listView() {
  logoutBtn.hidden = false;
  let notes;
  try { notes = await api('GET', '/api/notes'); } catch (e) { return; }
  const nodes = [el('button', { onclick: () => editView() }, 'New note')];
  if (!notes.length) nodes.push(el('p', { class: 'muted' }, 'No notes yet.'));
  for (const n of notes) {
    nodes.push(el('div', { class: 'card' },
      el('h3', {}, n.title),
      el('div', { class: 'muted' }, 'Updated ' + new Date(n.updated_at).toLocaleString() + (n.shared ? ' · shared' : ' · private')),
      el('p', { class: 'note-body' }, n.body.length > 200 ? n.body.slice(0, 200) + '…' : n.body),
      el('button', { class: 'secondary', onclick: () => editView(n) }, 'Edit'),
      el('button', { class: 'secondary', onclick: () => shareView(n) }, n.shared ? 'Sharing…' : 'Share'),
      el('button', { class: 'danger', onclick: async () => {
        if (confirm('Delete this note?')) { await api('DELETE', '/api/notes/' + n.id); listView(); }
      } }, 'Delete')));
  }
  show(...nodes);
}

function editView(n) {
  const msg = el('div', { class: 'err' });
  const title = el('input', { placeholder: 'Title', maxlength: 200, required: '' });
  const body = el('textarea', { placeholder: 'Write your note…' });
  title.value = n ? n.title : ''; body.value = n ? n.body : '';
  show(el('div', { class: 'card' },
    el('h2', {}, n ? 'Edit note' : 'New note'),
    el('form', { onsubmit: async ev => {
      ev.preventDefault();
      try {
        const payload = { title: title.value, body: body.value };
        if (n) await api('PUT', '/api/notes/' + n.id, payload); else await api('POST', '/api/notes', payload);
        listView();
      } catch (e) { msg.textContent = e.message; }
    } }, title, body, msg,
      el('button', { type: 'submit' }, 'Save'),
      el('button', { type: 'button', class: 'secondary', onclick: listView }, 'Cancel'))));
}

async function shareView(n) {
  try {
    const { share_token } = await api('POST', '/api/notes/' + n.id + '/share');
    const url = location.origin + '/s/' + share_token;
    show(el('div', { class: 'card' },
      el('h2', {}, 'Share "' + n.title + '"'),
      el('p', {}, 'Anyone with this link can read this note (no account needed):'),
      el('div', { class: 'sharebox' }, url),
      el('p', {},
        el('button', { onclick: () => navigator.clipboard && navigator.clipboard.writeText(url) }, 'Copy link'),
        el('button', { class: 'danger', onclick: async () => { await api('DELETE', '/api/notes/' + n.id + '/share'); listView(); } }, 'Stop sharing'),
        el('button', { class: 'secondary', onclick: listView }, 'Back'))));
  } catch (e) { alert(e.message); }
}

async function sharedView(t) {
  logoutBtn.hidden = true;
  try {
    const n = await api('GET', '/api/shared/' + encodeURIComponent(t));
    show(el('div', { class: 'card' }, el('h2', {}, n.title), el('div', { class: 'note-body' }, n.body)));
  } catch (e) {
    show(el('div', { class: 'card' }, 'This shared note does not exist or is no longer shared.'));
  }
}

function route() {
  const m = location.pathname.match(/^\/s\/([^/]+)$/);
  if (m) return sharedView(m[1]);
  return token ? listView() : authView();
}
route();
