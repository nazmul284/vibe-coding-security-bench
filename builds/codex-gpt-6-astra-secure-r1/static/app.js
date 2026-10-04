'use strict';
const $ = id => document.getElementById(id);
// Tokens live only in memory: reloading the page requires logging in again.
let token = null, notes = [], current = null, dirty = false, signup = false;
function message(text = '', error = false) { $('status').textContent = text; $('status').classList.toggle('error', error); }
async function api(path, method = 'GET', body) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(`/api${path}`, {method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store', credentials: 'omit'});
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    if (response.status === 401 && token) { token = null; showAuth(); }
    throw new Error(data.error || 'Something went wrong. Please try again.');
  }
  return data;
}
function showAuth() { notes = []; current = null; dirty = false; $('note-form').reset(); $('note-list').replaceChildren(); $('share-url').value = ''; $('workspace').hidden = true; $('logout').hidden = true; $('auth').hidden = false; }
function canLeave() { return !dirty || confirm('Discard your unsaved changes?'); }
function renderList() {
  const query = $('search').value.toLowerCase();
  $('note-list').replaceChildren();
  const filtered = notes.filter(n => `${n.title} ${n.body}`.toLowerCase().includes(query));
  if (!filtered.length) { const p = document.createElement('p'); p.textContent = notes.length ? 'No matching notes.' : 'Your ideas will feel at home here.'; $('note-list').append(p); }
  filtered.forEach(note => {
    const button = document.createElement('button'); button.className = 'note-item'; button.classList.toggle('active', note.id === current);
    const title = document.createElement('strong'); title.textContent = note.title;
    const preview = document.createElement('span'); preview.textContent = note.body.slice(0, 70) || 'An open page…';
    button.append(title, preview); button.onclick = () => { if (canLeave()) openNote(note); }; $('note-list').append(button);
  });
}
function openNote(note = null) {
  current = note?.id || null; dirty = false;
  $('empty').hidden = true; $('note-form').hidden = false;
  $('note-title').value = note?.title || ''; $('note-body').value = note?.body || '';
  $('privacy').textContent = note?.is_shared ? 'Shared by link' : 'Private';
  $('saved-at').textContent = note ? `Saved ${new Date(note.updated_at * 1000).toLocaleDateString()}` : 'Unsaved note';
  $('delete').hidden = !note; $('share').hidden = !note; $('revoke').hidden = !note?.is_shared;
  $('share').textContent = note?.is_shared ? 'Replace share link' : 'Create share link';
  $('share-box').hidden = true; $('share-url').value = ''; renderList();
}
async function refresh() { notes = await api('/notes'); renderList(); }
function action(handler) { return async event => { event?.preventDefault(); try { await handler(event); } catch (error) { message(error.message, true); } }; }
$('toggle-auth').onclick = () => {
  signup = !signup; $('auth-title').textContent = signup ? 'Make yourself at home.' : 'Welcome back.';
  $('auth-description').textContent = signup ? 'Create your private space in a moment.' : 'Log in to pick up where you left off.';
  $('auth-submit').textContent = signup ? 'Create account →' : 'Log in →';
  $('toggle-auth').textContent = signup ? 'Already have an account? Log in' : 'New here? Create an account';
  $('password').autocomplete = signup ? 'new-password' : 'current-password'; $('password').minLength = signup ? 12 : 1;
  $('password-help').textContent = signup ? 'Use 12–128 characters. A long, unique passphrase works well.' : 'Keep your thoughts safe with a strong password.'; message();
};
$('auth-form').onsubmit = action(async () => {
  $('auth-submit').disabled = true;
  try {
    const details = {email: $('email').value, password: $('password').value};
    if (signup) await api('/signup', 'POST', details);
    const result = await api('/login', 'POST', details); token = result.token; $('password').value = '';
    $('auth').hidden = true; $('workspace').hidden = false; $('logout').hidden = false; $('note-form').hidden = true; $('empty').hidden = false;
    await refresh(); message();
  } finally { $('auth-submit').disabled = false; }
});
$('new-note').onclick = () => { if (canLeave()) { openNote(); $('note-title').focus(); message(); } };
$('search').oninput = renderList;
$('note-form').oninput = () => { dirty = true; $('saved-at').textContent = 'Unsaved changes'; };
$('note-form').onsubmit = action(async () => {
  const note = await api(current ? `/notes/${current}` : '/notes', current ? 'PUT' : 'POST', {title: $('note-title').value, body: $('note-body').value});
  dirty = false; current = note.id; await refresh(); openNote(note); message('Note saved.');
});
$('delete').onclick = action(async () => {
  if (!current || !confirm('Delete this note permanently? Its share link will stop working too.')) return;
  await api(`/notes/${current}`, 'DELETE'); current = null; dirty = false; $('note-form').hidden = true; $('empty').hidden = false; await refresh(); message('Note deleted.');
});
$('share').onclick = action(async () => {
  if (dirty) { message('Save your changes before sharing.', true); return; }
  if (!confirm('Anyone with the link will be able to read this note. Continue? Existing links will stop working.')) return;
  const result = await api(`/notes/${current}/share`, 'POST');
  await refresh(); openNote(notes.find(n => n.id === current));
  // Fragment keeps the capability out of page request URLs and referrers.
  $('share-url').value = `${location.origin}/share#${result.share_token}`; $('share-box').hidden = false; message('Share link created.');
});
$('revoke').onclick = action(async () => {
  await api(`/notes/${current}/share`, 'DELETE'); await refresh();
  $('privacy').textContent = 'Private'; $('revoke').hidden = true; $('share').textContent = 'Create share link'; $('share-box').hidden = true; $('share-url').value = ''; message('Sharing stopped. The old link no longer works.');
});
$('copy').onclick = action(async () => {
  try { await navigator.clipboard.writeText($('share-url').value); message('Link copied.'); }
  catch { $('share-url').focus(); $('share-url').select(); message('Select and copy the link above.'); }
});
$('logout').onclick = action(async () => { if (!canLeave()) return; await api('/logout', 'POST'); token = null; showAuth(); message('You are logged out.'); });
window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
if (location.pathname === '/share') {
  $('auth').hidden = true; $('shared').hidden = false;
  let loadVersion = 0;
  async function loadShared() {
    const version = ++loadVersion;
    const shareToken = location.hash.slice(1); history.replaceState(null, '', '/share');
    $('shared-title').textContent = ''; $('shared-body').textContent = ''; message();
    if (!/^[A-Za-z0-9_-]{43}$/.test(shareToken)) { message('This share link is invalid.', true); return; }
    try {
      const note = await api(`/shared/${encodeURIComponent(shareToken)}`);
      if (version !== loadVersion) return;
      $('shared-title').textContent = note.title; $('shared-body').textContent = note.body;
    } catch (error) { if (version === loadVersion) message(error.message, true); }
  }
  window.addEventListener('hashchange', loadShared);
  loadShared();
}
