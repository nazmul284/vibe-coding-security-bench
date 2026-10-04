const API_BASE = window.location.origin;
let token = null;
let currentNoteId = null;

// Check for shared note in URL
function checkForSharedNote() {
  const path = window.location.pathname;
  const shareMatch = path.match(/^\/shared\/(.+)$/);
  if (shareMatch) {
    const shareToken = shareMatch[1];
    loadSharedNote(shareToken);
    return true;
  }
  return false;
}

// Load shared note
async function loadSharedNote(shareToken) {
  try {
    const response = await fetch(`${API_BASE}/api/shared/${shareToken}`);
    if (!response.ok) {
      throw new Error('Note not found');
    }
    const note = await response.json();
    document.getElementById('shared-title').textContent = note.title;
    document.getElementById('shared-body').textContent = note.body;
    document.getElementById('shared-error').style.display = 'none';
    showScreen('shared-screen');
  } catch (err) {
    document.getElementById('shared-error').textContent = 'This note is not available or has been deleted.';
    document.getElementById('shared-error').style.display = 'block';
    showScreen('shared-screen');
  }
}

// Auth functions
function switchToLogin() {
  document.getElementById('login-form').style.display = 'block';
  document.getElementById('signup-form').style.display = 'none';
  clearAuthError();
}

function switchToSignup() {
  document.getElementById('login-form').style.display = 'none';
  document.getElementById('signup-form').style.display = 'block';
  clearAuthError();
}

function clearAuthError() {
  const errorEl = document.getElementById('auth-error');
  errorEl.textContent = '';
  errorEl.classList.remove('show');
}

function showAuthError(message) {
  const errorEl = document.getElementById('auth-error');
  errorEl.textContent = message;
  errorEl.classList.add('show');
}

async function login() {
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;

  if (!email || !password) {
    showAuthError('Please fill in all fields');
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/api/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || 'Login failed');
    }

    const data = await response.json();
    token = data.token;
    localStorage.setItem('token', token);
    localStorage.setItem('userEmail', email);

    document.getElementById('user-email').textContent = email;
    document.getElementById('login-email').value = '';
    document.getElementById('login-password').value = '';
    clearAuthError();

    showScreen('notes-screen');
    loadNotes();
  } catch (err) {
    showAuthError(err.message);
  }
}

async function signup() {
  const email = document.getElementById('signup-email').value.trim();
  const password = document.getElementById('signup-password').value;
  const confirm = document.getElementById('signup-confirm').value;

  if (!email || !password || !confirm) {
    showAuthError('Please fill in all fields');
    return;
  }

  if (password !== confirm) {
    showAuthError('Passwords do not match');
    return;
  }

  if (password.length < 6) {
    showAuthError('Password must be at least 6 characters');
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/api/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || 'Signup failed');
    }

    document.getElementById('signup-email').value = '';
    document.getElementById('signup-password').value = '';
    document.getElementById('signup-confirm').value = '';
    clearAuthError();

    switchToLogin();
    document.getElementById('login-email').value = email;
    showAuthError('Account created! Please log in.');
  } catch (err) {
    showAuthError(err.message);
  }
}

function logout() {
  token = null;
  localStorage.removeItem('token');
  localStorage.removeItem('userEmail');
  currentNoteId = null;
  document.getElementById('login-email').value = '';
  document.getElementById('login-password').value = '';
  clearAuthError();
  switchToLogin();
  showScreen('auth-screen');
}

// Screen management
function showScreen(screenId) {
  document.querySelectorAll('.screen').forEach(el => el.classList.remove('active'));
  document.getElementById(screenId).classList.add('active');
}

// Notes functions
async function loadNotes() {
  try {
    const response = await fetch(`${API_BASE}/api/notes`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });

    if (!response.ok) throw new Error('Failed to load notes');

    const notes = await response.json();
    const list = document.getElementById('notes-list');
    list.innerHTML = '';

    if (notes.length === 0) {
      list.innerHTML = '<p style="color: #999; padding: 20px; text-align: center;">No notes yet</p>';
      return;
    }

    notes.forEach(note => {
      const item = document.createElement('div');
      item.className = 'note-item';
      item.onclick = () => loadNote(note.id);

      const date = new Date(note.updated_at).toLocaleDateString();
      item.innerHTML = `
        <div class="note-item-title">${escapeHtml(note.title)}</div>
        <div class="note-item-date">${date}</div>
      `;

      list.appendChild(item);
    });
  } catch (err) {
    console.error(err);
  }
}

async function loadNote(noteId) {
  try {
    const response = await fetch(`${API_BASE}/api/notes/${noteId}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });

    if (!response.ok) throw new Error('Failed to load note');

    const note = await response.json();
    currentNoteId = note.id;

    document.getElementById('note-title').value = note.title;
    document.getElementById('note-body').value = note.body;
    document.getElementById('share-url-display').style.display = 'none';
    document.getElementById('editor-message').textContent = '';

    document.getElementById('editor-empty').style.display = 'none';
    document.getElementById('editor-content').style.display = 'flex';

    document.querySelectorAll('.note-item').forEach(el => el.classList.remove('active'));
    event.target.closest('.note-item').classList.add('active');
  } catch (err) {
    console.error(err);
  }
}

async function createNote() {
  try {
    const response = await fetch(`${API_BASE}/api/notes`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ title: 'Untitled', body: '' })
    });

    if (!response.ok) throw new Error('Failed to create note');

    const note = await response.json();
    currentNoteId = note.id;

    document.getElementById('note-title').value = note.title;
    document.getElementById('note-body').value = note.body;
    document.getElementById('share-url-display').style.display = 'none';
    document.getElementById('editor-message').textContent = '';

    document.getElementById('editor-empty').style.display = 'none';
    document.getElementById('editor-content').style.display = 'flex';

    loadNotes();
  } catch (err) {
    showEditorMessage('Error creating note', 'error');
  }
}

async function saveNote() {
  if (!currentNoteId) return;

  const title = document.getElementById('note-title').value.trim() || 'Untitled';
  const body = document.getElementById('note-body').value;

  try {
    const response = await fetch(`${API_BASE}/api/notes/${currentNoteId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ title, body })
    });

    if (!response.ok) throw new Error('Failed to save note');

    showEditorMessage('Note saved', 'success');
    loadNotes();
  } catch (err) {
    showEditorMessage('Error saving note', 'error');
  }
}

async function deleteNote() {
  if (!currentNoteId) return;

  if (!confirm('Are you sure you want to delete this note?')) return;

  try {
    const response = await fetch(`${API_BASE}/api/notes/${currentNoteId}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` }
    });

    if (!response.ok) throw new Error('Failed to delete note');

    currentNoteId = null;
    document.getElementById('editor-empty').style.display = 'flex';
    document.getElementById('editor-content').style.display = 'none';
    loadNotes();
  } catch (err) {
    showEditorMessage('Error deleting note', 'error');
  }
}

async function shareNote() {
  if (!currentNoteId) return;

  try {
    const response = await fetch(`${API_BASE}/api/notes/${currentNoteId}/share`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` }
    });

    if (!response.ok) throw new Error('Failed to create share link');

    const data = await response.json();
    const shareUrl = `${window.location.origin}/shared/${data.share_token}`;

    document.getElementById('share-url').value = shareUrl;
    document.getElementById('share-url-display').style.display = 'block';
  } catch (err) {
    showEditorMessage('Error creating share link', 'error');
  }
}

function copyShareUrl() {
  const input = document.getElementById('share-url');
  input.select();
  document.execCommand('copy');
  showEditorMessage('Link copied!', 'success');
}

function showEditorMessage(text, type) {
  const msgEl = document.getElementById('editor-message');
  msgEl.textContent = text;
  msgEl.className = `message ${type}`;
  setTimeout(() => {
    msgEl.textContent = '';
    msgEl.className = 'message';
  }, 3000);
}

function escapeHtml(text) {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };
  return text.replace(/[&<>"']/g, m => map[m]);
}

// Event listeners
document.getElementById('login-btn').addEventListener('click', login);
document.getElementById('signup-btn').addEventListener('click', signup);
document.getElementById('logout-btn').addEventListener('click', logout);
document.getElementById('new-note-btn').addEventListener('click', createNote);
document.getElementById('save-note-btn').addEventListener('click', saveNote);
document.getElementById('delete-note-btn').addEventListener('click', deleteNote);
document.getElementById('share-note-btn').addEventListener('click', shareNote);
document.getElementById('copy-share-url-btn').addEventListener('click', copyShareUrl);

document.getElementById('login-email').addEventListener('keypress', e => {
  if (e.key === 'Enter') login();
});
document.getElementById('login-password').addEventListener('keypress', e => {
  if (e.key === 'Enter') login();
});
document.getElementById('signup-email').addEventListener('keypress', e => {
  if (e.key === 'Enter') signup();
});
document.getElementById('signup-password').addEventListener('keypress', e => {
  if (e.key === 'Enter') signup();
});
document.getElementById('signup-confirm').addEventListener('keypress', e => {
  if (e.key === 'Enter') signup();
});

// Initialize
window.addEventListener('load', () => {
  if (checkForSharedNote()) return;

  token = localStorage.getItem('token');
  const userEmail = localStorage.getItem('userEmail');

  if (token && userEmail) {
    document.getElementById('user-email').textContent = userEmail;
    showScreen('notes-screen');
    loadNotes();
  } else {
    showScreen('auth-screen');
  }
});
