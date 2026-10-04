const $ = (selector) => document.querySelector(selector);
let mode = 'login';
let notes = [];
let currentId = null;
let token = localStorage.getItem('noteshare_token');

async function api(path, options = {}, auth = true) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers['Content-Type'] = 'application/json';
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { ...options, headers });
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) {
    if (response.status === 401 && auth) showAuth();
    throw new Error(data.error || 'Something went wrong');
  }
  return data;
}

function showAuth() {
  token = null;
  localStorage.removeItem('noteshare_token');
  $('#auth-view').classList.remove('hidden');
  $('#app-view').classList.add('hidden');
  $('#shared-view').classList.add('hidden');
  $('#logout').classList.add('hidden');
}

async function showApp() {
  $('#auth-view').classList.add('hidden');
  $('#shared-view').classList.add('hidden');
  $('#app-view').classList.remove('hidden');
  $('#logout').classList.remove('hidden');
  await loadNotes();
}

async function loadNotes(selectId = currentId) {
  notes = await api('/api/notes');
  const list = $('#note-list');
  list.replaceChildren();
  notes.forEach(note => {
    const button = document.createElement('button');
    button.className = `note-item${note.id === selectId ? ' active' : ''}`;
    const title = document.createElement('strong');
    title.textContent = note.title;
    const preview = document.createElement('span');
    preview.textContent = note.body || 'Empty note';
    button.append(title, preview);
    button.addEventListener('click', () => openNote(note.id));
    list.append(button);
  });
  if (selectId && notes.some(n => n.id === selectId)) openNote(selectId);
  else if (notes.length) openNote(notes[0].id);
  else closeEditor();
}

function openNote(id) {
  const note = notes.find(n => n.id === id);
  if (!note) return;
  currentId = id;
  $('#empty-state').classList.add('hidden');
  $('#note-form').classList.remove('hidden');
  $('#note-title').value = note.title;
  $('#note-body').value = note.body;
  $('#share-box').classList.add('hidden');
  $('#note-error').textContent = '';
  $('#save-status').textContent = `Updated ${new Date(note.updated_at).toLocaleString()}`;
  document.querySelectorAll('.note-item').forEach((item, i) => item.classList.toggle('active', notes[i].id === id));
}

function closeEditor() {
  currentId = null;
  $('#note-form').classList.add('hidden');
  $('#empty-state').classList.remove('hidden');
}

async function createNote() {
  try {
    const note = await api('/api/notes', { method: 'POST', body: JSON.stringify({ title: 'Untitled note', body: '' }) });
    currentId = note.id;
    await loadNotes(note.id);
    $('#note-title').select();
  } catch (error) { alert(error.message); }
}

document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => {
  mode = tab.dataset.mode;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === tab));
  $('#auth-submit').textContent = mode === 'login' ? 'Log in' : 'Create account';
  $('#auth-error').textContent = '';
}));

$('#auth-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('#auth-error').textContent = '';
  const credentials = { email: $('#email').value, password: $('#password').value };
  try {
    if (mode === 'signup') await api('/api/signup', { method: 'POST', body: JSON.stringify(credentials) }, false);
    const result = await api('/api/login', { method: 'POST', body: JSON.stringify(credentials) }, false);
    token = result.token;
    localStorage.setItem('noteshare_token', token);
    await showApp();
  } catch (error) { $('#auth-error').textContent = error.message; }
});

$('#note-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!currentId) return;
  $('#note-error').textContent = '';
  try {
    const note = await api(`/api/notes/${currentId}`, { method: 'PUT', body: JSON.stringify({ title: $('#note-title').value, body: $('#note-body').value }) });
    $('#save-status').textContent = 'Saved just now';
    await loadNotes(note.id);
  } catch (error) { $('#note-error').textContent = error.message; }
});

$('#delete-note').addEventListener('click', async () => {
  if (!currentId || !confirm('Delete this note? This cannot be undone.')) return;
  try { await api(`/api/notes/${currentId}`, { method: 'DELETE' }); currentId = null; await loadNotes(); }
  catch (error) { $('#note-error').textContent = error.message; }
});

$('#share-note').addEventListener('click', async () => {
  try {
    const result = await api(`/api/notes/${currentId}/share`, { method: 'POST' });
    $('#share-link').value = `${location.origin}/?share=${encodeURIComponent(result.share_token)}`;
    $('#share-box').classList.remove('hidden');
  } catch (error) { $('#note-error').textContent = error.message; }
});

$('#copy-link').addEventListener('click', async () => {
  await navigator.clipboard.writeText($('#share-link').value);
  $('#copy-link').textContent = 'Copied!';
  setTimeout(() => $('#copy-link').textContent = 'Copy', 1500);
});

$('#new-note').addEventListener('click', createNote);
$('#empty-new').addEventListener('click', createNote);
$('#logout').addEventListener('click', showAuth);

async function start() {
  const shared = new URLSearchParams(location.search).get('share');
  if (shared) {
    $('#auth-view').classList.add('hidden');
    try {
      const note = await api(`/api/shared/${encodeURIComponent(shared)}`, {}, false);
      $('#shared-title').textContent = note.title;
      $('#shared-date').textContent = `Shared note · Updated ${new Date(note.updated_at).toLocaleString()}`;
      $('#shared-body').textContent = note.body;
      $('#shared-view').classList.remove('hidden');
    } catch (error) {
      $('#shared-title').textContent = 'This share link is not available.';
      $('#shared-body').textContent = error.message;
      $('#shared-view').classList.remove('hidden');
    }
  } else if (token) {
    try { await showApp(); } catch { showAuth(); }
  }
}
start();
