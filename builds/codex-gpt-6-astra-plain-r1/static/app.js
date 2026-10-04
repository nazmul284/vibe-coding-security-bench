'use strict';
const $ = id => document.getElementById(id);
let token = sessionStorage.getItem('noteshare-token');
let email = sessionStorage.getItem('noteshare-email') || '';
let notes = [], activeId = null, dirty = false, mode = 'login', saving = false;
let toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 4500); }
async function api(path, method = 'GET', body) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response;
  try { response = await fetch(path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)}); }
  catch { throw new Error('Could not reach NoteShare. Check your connection and try again.'); }
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    if (response.status === 401 && !['/api/login', '/api/signup'].includes(path)) { clearSession(); showView('auth-view'); }
    throw new Error(data.error || 'Something went wrong. Please try again.');
  }
  return data;
}
function clearSession() { token = null; sessionStorage.removeItem('noteshare-token'); sessionStorage.removeItem('noteshare-email'); }
function showView(view) {
  ['auth-view', 'workspace', 'shared-view'].forEach(id => $(id).hidden = id !== view);
  $('account').hidden = view !== 'workspace'; $('header-caption').hidden = view === 'workspace';
  $('account-email').textContent = email;
}
function setMode(next) {
  mode = next;
  $('login-tab').classList.toggle('selected', mode === 'login');
  $('signup-tab').classList.toggle('selected', mode === 'signup');
  $('auth-heading').textContent = mode === 'login' ? 'Your thoughts belong here.' : 'A fresh page awaits.';
  $('auth-caption').textContent = mode === 'login' ? 'Log in to pick up where you left off.' : 'Create your own space in just a moment.';
  $('auth-submit').textContent = mode === 'login' ? 'Log in ↗' : 'Create account ↗';
  $('password').autocomplete = mode === 'login' ? 'current-password' : 'new-password';
  $('auth-error').textContent = '';
}
$('login-tab').onclick = () => setMode('login');
$('signup-tab').onclick = () => setMode('signup');
$('auth-form').onsubmit = async event => {
  event.preventDefault(); $('auth-error').textContent = ''; $('auth-submit').disabled = true;
  const credentials = {email: $('email').value.trim(), password: $('password').value};
  try {
    if (mode === 'signup') await api('/api/signup', 'POST', credentials);
    const result = await api('/api/login', 'POST', credentials);
    token = result.token; email = credentials.email.toLowerCase();
    sessionStorage.setItem('noteshare-token', token); sessionStorage.setItem('noteshare-email', email);
    $('password').value = ''; notes = []; activeId = null; dirty = false;
    await loadWorkspace();
  } catch (error) { $('auth-error').textContent = error.message; }
  finally { $('auth-submit').disabled = false; }
};
function canLeave() { return !dirty || confirm('You have unsaved changes. Discard them?'); }
$('logout').onclick = async () => {
  if (!canLeave()) return;
  try { await api('/api/logout', 'POST'); clearSession(); notes = []; activeId = null; dirty = false; $('note-title').value = ''; $('note-body').value = ''; $('notes-list').replaceChildren(); showView('auth-view'); }
  catch (error) { toast(error.message); }
};
function date(value) { return new Date(value).toLocaleDateString(undefined, {month:'short', day:'numeric', year:'numeric'}); }
async function loadWorkspace() {
  notes = await api('/api/notes'); showView('workspace'); renderList();
  if (notes.length) openNote(notes[0]);
  else { $('editor').hidden = true; $('empty-state').hidden = false; }
}
function renderList() {
  const query = $('search').value.toLowerCase();
  const filtered = notes.filter(n => `${n.title} ${n.body}`.toLowerCase().includes(query));
  $('note-count').textContent = notes.length; $('notes-list').replaceChildren();
  for (const note of filtered) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'note-item' + (note.id === activeId ? ' active' : '');
    const title = document.createElement('strong'); title.textContent = note.title;
    const preview = document.createElement('p'); preview.textContent = note.body || 'A little room for a thought…';
    const meta = document.createElement('small'); meta.textContent = `${date(note.updated_at)} · ${note.shared ? 'Shared' : 'Private'}`;
    button.append(title, preview, meta); button.onclick = () => { if (saving) return; if (canLeave()) openNote(note); }; $('notes-list').append(button);
  }
  if (!filtered.length) { const p = document.createElement('p'); p.className = 'list-empty'; p.textContent = query ? 'No notes match your search.' : 'Your ideas will find a home here.'; $('notes-list').append(p); }
}
function openNote(note) {
  activeId = note?.id || null; dirty = false;
  $('empty-state').hidden = true; $('editor').hidden = false;
  $('note-title').value = note?.title || ''; $('note-body').value = note?.body || '';
  $('share-note').disabled = !activeId; $('delete-note').disabled = !activeId;
  $('note-status').textContent = note?.shared ? '↗ Shared note' : '◈ Private note';
  $('save-status').textContent = note ? `Last saved ${date(note.updated_at)}` : 'Not saved yet'; renderList();
}
function newNote() { if (saving || !canLeave()) return; openNote(null); $('note-title').focus(); }
$('new-note').onclick = $('empty-new').onclick = newNote;
$('search').oninput = renderList;
['note-title', 'note-body'].forEach(id => $(id).oninput = () => { dirty = true; $('save-status').textContent = 'Unsaved changes'; });
async function save() {
  if (saving) return null;
  if (!$('editor').reportValidity()) return null;
  saving = true; $('save-note').disabled = true;
  $('note-title').readOnly = true; $('note-body').readOnly = true;
  try {
    const note = await api(activeId ? `/api/notes/${activeId}` : '/api/notes', activeId ? 'PUT' : 'POST', {title:$('note-title').value, body:$('note-body').value});
    notes = [note, ...notes.filter(n => n.id !== note.id)]; openNote(note); toast('Note saved. A thought well kept.'); return note;
  } catch (error) { toast(error.message); return null; }
  finally { saving = false; $('save-note').disabled = false; $('note-title').readOnly = false; $('note-body').readOnly = false; }
}
$('editor').onsubmit = event => { event.preventDefault(); save(); };
$('delete-note').onclick = async () => {
  if (saving || !activeId || !confirm('Delete this note permanently? Its share link will also stop working.')) return;
  $('delete-note').disabled = true;
  try { await api(`/api/notes/${activeId}`, 'DELETE'); notes = notes.filter(n => n.id !== activeId); activeId = null; dirty = false; if (notes.length) openNote(notes[0]); else { $('editor').hidden = true; $('empty-state').hidden = false; renderList(); } toast('Note deleted.'); }
  catch (error) { toast(error.message); }
  finally { $('delete-note').disabled = !activeId; }
};
$('share-note').onclick = async () => {
  if (saving || !activeId) return;
  if (dirty && !(await save())) return;
  const current = notes.find(n => n.id === activeId);
  if (current?.shared && !confirm('Create a new share link? The previous link will stop working.')) return;
  $('share-note').disabled = true;
  try {
    const data = await api(`/api/notes/${activeId}/share`, 'POST');
    if (current) current.shared = true;
    $('note-status').textContent = '↗ Shared note'; renderList();
    $('share-url').value = `${location.origin}/shared/${data.share_token}`;
    $('copy-link').textContent = 'Copy'; $('share-dialog').showModal();
  } catch (error) { toast(error.message); }
  finally { $('share-note').disabled = false; }
};
$('copy-link').onclick = async () => {
  try { await navigator.clipboard.writeText($('share-url').value); $('copy-link').textContent = 'Copied!'; }
  catch { $('share-url').select(); toast('Select and copy the link from the field.'); }
};
$('revoke-share').onclick = async () => {
  try { await api(`/api/notes/${activeId}/share`, 'DELETE'); const note = notes.find(n => n.id === activeId); if (note) note.shared = false; $('note-status').textContent = '◈ Private note'; renderList(); $('share-dialog').close(); toast('Sharing turned off. Your note is private again.'); }
  catch (error) { toast(error.message); }
};
window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
async function init() {
  const shared = location.pathname.match(/^\/shared\/([A-Za-z0-9_-]+)$/);
  if (shared) {
    showView('shared-view'); $('shared-title').textContent = 'Opening your note…';
    try { const note = await api(`/api/shared/${shared[1]}`); $('shared-title').textContent = note.title; $('shared-body').textContent = note.body; $('shared-date').textContent = `Updated ${date(note.updated_at)}`; document.title = `${note.title} — NoteShare`; }
    catch (error) { $('shared-title').textContent = 'This page is quiet.'; $('shared-body').textContent = error.message; }
  } else if (token) {
    try { await loadWorkspace(); } catch (error) { showView('auth-view'); $('auth-error').textContent = error.message; }
  } else showView('auth-view');
}
init();
