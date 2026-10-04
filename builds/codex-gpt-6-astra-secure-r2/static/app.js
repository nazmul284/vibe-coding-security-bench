'use strict';
const $ = id => document.getElementById(id);
let token = null, signup = false, notes = [], current = null, dirty = false;
function message(text) { $('message').textContent = text; }
async function api(path, method = 'GET', data) {
  const headers = {}; if (token) headers.Authorization = `Bearer ${token}`;
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { method, headers, body: data === undefined ? undefined : JSON.stringify(data), credentials: 'omit' });
  const result = res.status === 204 ? null : await res.json();
  if (!res.ok) { if (res.status === 401 && token) { token = null; showAuth(); } throw new Error(result.error || 'Request failed.'); }
  return result;
}
function showAuth() { $('auth').hidden = false; $('workspace').hidden = true; $('account').hidden = true; $('password').value = ''; notes = []; current = null; dirty = false; $('list').replaceChildren(); $('title').value = ''; $('body').value = ''; $('share-url').value = ''; }
function discard() { return !dirty || confirm('Discard your unsaved changes?'); }
function select(note) {
  current = note; dirty = false; $('title').value = note?.title || ''; $('body').value = note?.body || '';
  $('privacy').textContent = note?.shared ? 'Shared by link' : 'Private';
  $('saved').textContent = note ? 'Saved ' + new Date(note.updated_at * 1000).toLocaleDateString() : 'New note';
  $('share').hidden = $('delete').hidden = !note; $('revoke').hidden = !note?.shared;
  $('share').textContent = note?.shared ? 'Replace share link' : 'Create share link';
  $('share-box').hidden = true; $('share-url').value = ''; render();
}
function render() {
  $('count').textContent = `(${notes.length})`; $('empty').hidden = notes.length > 0; $('list').replaceChildren();
  for (const note of notes) {
    const button = document.createElement('button'); button.className = 'note-button' + (current?.id === note.id ? ' active' : '');
    const title = document.createElement('strong'); title.textContent = note.title;
    const preview = document.createElement('span'); preview.textContent = note.body.slice(0, 80) || 'An empty page, full of possibilities.';
    button.append(title, preview); button.onclick = () => { if (discard()) select(note); }; $('list').append(button);
  }
}
async function refresh(id) { notes = await api('/api/notes'); select(notes.find(n => n.id === id) || null); }
function action(fn) { return async event => { event?.preventDefault(); message(''); const button = event?.submitter || event?.currentTarget; if (button?.tagName === 'BUTTON') button.disabled = true; try { await fn(event); } catch (err) { message(err.message || 'Connection failed. Please try again.'); } finally { if (button?.tagName === 'BUTTON') button.disabled = false; } }; }
$('toggle-auth').onclick = () => { signup = !signup; $('auth-title').textContent = signup ? 'Make a little space.' : 'Your notebook awaits.'; $('auth-submit').textContent = signup ? 'Create account' : 'Log in'; $('toggle-auth').textContent = signup ? 'Already have an account? Log in' : 'New here? Create an account'; $('password').autocomplete = signup ? 'new-password' : 'current-password'; $('password').minLength = signup ? 12 : 1; message(''); };
$('auth-form').onsubmit = action(async () => {
  const credentials = {email: $('email').value, password: $('password').value};
  if (signup) await api('/api/signup', 'POST', credentials);
  token = (await api('/api/login', 'POST', credentials)).token;
  $('password').value = ''; $('auth').hidden = true; $('workspace').hidden = false; $('account').hidden = false;
  await refresh();
});
$('logout').onclick = action(async () => { if (!discard()) return; await api('/api/logout', 'POST'); token = null; showAuth(); });
$('new').onclick = () => { if (discard()) { select(null); $('title').focus(); } };
$('title').oninput = $('body').oninput = () => { dirty = true; $('saved').textContent = 'Unsaved changes'; };
$('editor').onsubmit = action(async () => { const saved = await api(current ? `/api/notes/${current.id}` : '/api/notes', current ? 'PUT' : 'POST', {title: $('title').value, body: $('body').value}); await refresh(saved.id); message('Note saved.'); });
$('delete').onclick = action(async () => { if (!current || !confirm('Delete this note permanently? Its share link will also stop working.')) return; await api(`/api/notes/${current.id}`, 'DELETE'); await refresh(); message('Note deleted.'); });
$('share').onclick = action(async () => {
  if (dirty) { message('Save your changes before sharing.'); return; }
  if (!confirm('Anyone with the link can read this note and future saved edits. Creating a new link disables the previous one. Continue?')) return;
  const result = await api(`/api/notes/${current.id}/share`, 'POST'); const id = current.id;
  await refresh(id); $('share-url').value = `${location.origin}/s/${result.share_token}`; $('share-box').hidden = false;
});
$('revoke').onclick = action(async () => { if (!discard()) return; const id = current.id; await api(`/api/notes/${id}/share`, 'DELETE'); await refresh(id); message('Sharing turned off. The old link no longer works.'); });
$('copy').onclick = action(async () => { try { await navigator.clipboard.writeText($('share-url').value); message('Link copied.'); } catch { $('share-url').select(); message('Select and copy the link above.'); } });
window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
if (location.pathname.startsWith('/s/')) {
  $('auth').hidden = true; $('shared').hidden = false;
  api('/api/shared/' + encodeURIComponent(location.pathname.slice(3))).then(note => { $('shared-title').textContent = note.title; $('shared-body').textContent = note.body; }).catch(() => { $('shared-title').textContent = 'This note isn’t available.'; $('shared-body').textContent = 'The link may have been replaced, or the owner may have stopped sharing this note.'; });
}
