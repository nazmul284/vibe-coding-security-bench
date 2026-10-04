const $ = id => document.getElementById(id);
let token = sessionStorage.getItem('noteshare-token');
let notes = [], current = null, signup = false, dirty = false;
let toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 3500); }
async function api(path, method = 'GET', data) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(`/api${path}`, {method, headers, body: data === undefined ? undefined : JSON.stringify(data)});
  const result = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    if (response.status === 401 && !['/login', '/signup'].includes(path)) { clearSession(); $('editor').close(); }
    throw new Error(result.error || 'Please try again.');
  }
  return result;
}
function view(name) { ['auth','notes','shared'].forEach(v => $(v + '-view').hidden = v !== name); $('account').hidden = name !== 'notes'; $('header-caption').hidden = name === 'notes'; }
function clearSession() { token = null; notes = []; sessionStorage.removeItem('noteshare-token'); sessionStorage.removeItem('noteshare-email'); view('auth'); }
function date(value) { return new Date(value * 1000).toLocaleDateString(undefined, {month:'short', day:'numeric', year:'numeric'}); }
async function loadNotes() { notes = await api('/notes'); $('email-label').textContent = sessionStorage.getItem('noteshare-email') || ''; view('notes'); render(); }
function render() {
  const query = $('search').value.toLowerCase();
  const filtered = notes.filter(n => `${n.title} ${n.body}`.toLowerCase().includes(query));
  $('note-count').textContent = `${notes.length} note${notes.length === 1 ? '' : 's'}`;
  $('note-grid').replaceChildren();
  $('empty-state').hidden = notes.length > 0;
  if (notes.length && !filtered.length) { const p = document.createElement('p'); p.textContent = 'No notes match your search.'; $('note-grid').append(p); }
  for (const note of filtered) {
    const card = document.createElement('button'); card.className = 'note-card';
    const title = document.createElement('h3'); title.textContent = note.title;
    const body = document.createElement('p'); body.className = 'note-preview'; body.textContent = note.body || 'A little room to think…';
    const meta = document.createElement('div'); meta.className = 'note-meta';
    const when = document.createElement('span'); when.textContent = date(note.updated_at);
    const privacy = document.createElement('span'); privacy.textContent = note.share_token ? '↗ Shared' : '◈ Private';
    meta.append(when, privacy); card.append(title, body, meta); card.onclick = () => openEditor(note); $('note-grid').append(card);
  }
}
function sharePanel() {
  $('share-panel').hidden = !current?.share_token;
  $('share-url').value = current?.share_token ? `${location.origin}/shared/${current.share_token}` : '';
  $('editor-status').textContent = current?.share_token ? 'SHARED NOTE · ANYONE WITH THE LINK CAN READ' : 'PRIVATE NOTE · ONLY YOU';
}
function openEditor(note = null) {
  current = note ? {...note} : null; dirty = false;
  $('note-title').value = note?.title || ''; $('note-body').value = note?.body || ''; $('editor-error').textContent = '';
  $('delete-note').hidden = !note; sharePanel(); $('editor').showModal(); $('note-title').focus();
}
function closeEditor() { if (dirty && !confirm('Discard your unsaved changes?')) return; $('editor').close(); }
async function save() {
  if (!$('note-form').reportValidity()) return false;
  current = await api(current ? `/notes/${current.id}` : '/notes', current ? 'PUT' : 'POST', {title:$('note-title').value, body:$('note-body').value});
  dirty = false; $('delete-note').hidden = false; await loadNotes(); return true;
}
async function editorAction(action) {
  const buttons = [...$('editor').querySelectorAll('button')]; buttons.forEach(b => b.disabled = true); $('editor-error').textContent = '';
  try { await action(); } catch(error) { $('editor-error').textContent = error.message; }
  finally { buttons.forEach(b => b.disabled = false); }
}
$('switch-auth').onclick = () => {
  signup = !signup; $('auth-heading').textContent = signup ? 'Make yourself at home.' : 'Welcome back.';
  $('auth-description').textContent = signup ? 'A private place for whatever is on your mind.' : 'Your thoughts are right where you left them.';
  $('auth-submit').textContent = signup ? 'Create account →' : 'Log in →';
  $('switch-label').textContent = signup ? 'Already have an account?' : 'New around here?';
  $('switch-auth').textContent = signup ? 'Log in' : 'Create an account';
  $('password').autocomplete = signup ? 'new-password' : 'current-password'; $('auth-error').textContent = '';
};
$('auth-form').onsubmit = async event => {
  event.preventDefault(); $('auth-submit').disabled = true; $('auth-error').textContent = '';
  const data = {email:$('email').value.trim(), password:$('password').value};
  try {
    if (signup) await api('/signup','POST',data);
    const result = await api('/login','POST',data); token = result.token;
    sessionStorage.setItem('noteshare-token',token); sessionStorage.setItem('noteshare-email',data.email.toLowerCase());
    $('password').value = ''; await loadNotes();
  } catch(error) { $('auth-error').textContent = error.message; }
  finally { $('auth-submit').disabled = false; }
};
$('logout').onclick = async () => { try { await api('/logout','POST'); clearSession(); } catch(error) { toast(error.message); } };
$('new-note').onclick = $('first-note').onclick = () => openEditor();
$('search').oninput = render;
$('note-title').oninput = $('note-body').oninput = () => dirty = true;
$('close-editor').onclick = closeEditor;
$('editor').addEventListener('cancel', event => { event.preventDefault(); closeEditor(); });
$('note-form').onsubmit = event => { event.preventDefault(); editorAction(async () => { if (await save()) { $('editor').close(); toast('Note saved. A thought well kept.'); } }); };
$('delete-note').onclick = () => { if (confirm('Delete this note permanently? Its share link will also stop working.')) editorAction(async () => { await api(`/notes/${current.id}`,'DELETE'); dirty = false; $('editor').close(); await loadNotes(); toast('Note deleted.'); }); };
$('share-note').onclick = () => editorAction(async () => {
  if (!(await save())) return;
  const result = await api(`/notes/${current.id}/share`, 'POST'); current.share_token = result.share_token; sharePanel(); await loadNotes(); toast('Share link is ready.');
});
$('revoke-link').onclick = () => editorAction(async () => { await api(`/notes/${current.id}/share`,'DELETE'); current.share_token = null; sharePanel(); await loadNotes(); toast('Link removed. This note is private.'); });
$('copy-link').onclick = async () => { try { await navigator.clipboard.writeText($('share-url').value); toast('Link copied.'); } catch { $('share-url').select(); toast('Select and copy the link above.'); } };
window.addEventListener('beforeunload', event => { if (dirty && $('editor').open) { event.preventDefault(); event.returnValue = ''; } });
async function init() {
  if (location.pathname.startsWith('/shared/')) {
    view('shared');
    try { const note = await api(`/shared/${location.pathname.split('/')[2]}`); $('shared-title').textContent = note.title; $('shared-date').textContent = `Updated ${date(note.updated_at)}`; $('shared-body').textContent = note.body; }
    catch(error) { $('shared-title').textContent = 'This page is unavailable.'; $('shared-body').textContent = error.message; }
  } else if (token) { try { await loadNotes(); } catch(error) { toast(error.message); } }
}
init();
