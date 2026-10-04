let currentNoteId = null;
let notes = [];
let token = localStorage.getItem('token');

if (!token) {
  window.location.href = '/';
}

function getToken() {
  return localStorage.getItem('token');
}

async function loadNotes() {
  try {
    const response = await fetch('/api/notes', {
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });

    if (response.status === 403) {
      localStorage.removeItem('token');
      window.location.href = '/';
      return;
    }

    if (response.status === 200) {
      notes = await response.json();
      displayNotes();
    }
  } catch (err) {
    console.error('Error loading notes:', err);
  }
}

function displayNotes() {
  const notesList = document.getElementById('notesList');
  notesList.innerHTML = '';

  if (notes.length === 0) {
    notesList.innerHTML = '<p style="color: #999; margin-top: 20px;">No notes yet. Create one to get started!</p>';
    return;
  }

  notes.forEach(note => {
    const noteItem = document.createElement('div');
    noteItem.className = 'note-item';
    if (note.id === currentNoteId) noteItem.classList.add('active');

    noteItem.innerHTML = `
      <div class="note-item-title">${escapeHtml(note.title || 'Untitled')}</div>
      <div class="note-item-date">${new Date(note.updated_at).toLocaleDateString()}</div>
    `;

    noteItem.onclick = () => editNote(note);
    notesList.appendChild(noteItem);
  });
}

function openNewNoteModal() {
  currentNoteId = null;
  document.getElementById('noteTitle').value = '';
  document.getElementById('noteBody').value = '';
  document.getElementById('noteEditor').style.display = 'flex';
  document.getElementById('shareSection').style.display = 'none';
  document.getElementById('noteTitle').focus();
}

async function editNote(note) {
  currentNoteId = note.id;
  document.getElementById('noteTitle').value = note.title;
  document.getElementById('noteBody').value = note.body;
  document.getElementById('noteEditor').style.display = 'flex';
  displayNotes();

  const shareLink = `${window.location.origin}/view.html?share=${await getShareToken(note.id)}`;
  document.getElementById('shareLink').value = shareLink;
  document.getElementById('shareSection').style.display = 'block';
}

async function getShareToken(noteId) {
  try {
    const response = await fetch(`/api/notes/${noteId}/share`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });

    if (response.status === 201) {
      const data = await response.json();
      return data.share_token;
    }
  } catch (err) {
    console.error('Error getting share token:', err);
  }
  return '';
}

async function saveNote() {
  const title = document.getElementById('noteTitle').value;
  const body = document.getElementById('noteBody').value;

  if (!title.trim()) {
    alert('Please enter a note title');
    return;
  }

  try {
    let response;
    if (currentNoteId) {
      response = await fetch(`/api/notes/${currentNoteId}`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${getToken()}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ title, body })
      });
    } else {
      response = await fetch('/api/notes', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${getToken()}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ title, body })
      });
    }

    if (response.status === 200 || response.status === 201) {
      loadNotes();
      closeEditor();
    } else {
      alert('Error saving note');
    }
  } catch (err) {
    alert('Error saving note');
  }
}

function closeEditor() {
  document.getElementById('noteEditor').style.display = 'none';
  currentNoteId = null;
  displayNotes();
}

async function deleteNote() {
  if (!currentNoteId) return;

  if (!confirm('Are you sure you want to delete this note?')) {
    return;
  }

  try {
    const response = await fetch(`/api/notes/${currentNoteId}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });

    if (response.status === 200) {
      loadNotes();
      closeEditor();
    }
  } catch (err) {
    alert('Error deleting note');
  }
}

function copyShareLink() {
  const shareLink = document.getElementById('shareLink').value;
  navigator.clipboard.writeText(shareLink).then(() => {
    const btn = event.target;
    const originalText = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => {
      btn.textContent = originalText;
    }, 2000);
  });
}

function logout() {
  if (confirm('Are you sure you want to logout?')) {
    localStorage.removeItem('token');
    window.location.href = '/';
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Add delete button to the editor
const editorHeader = document.querySelector('.editor-header');
const editorButtons = editorHeader.querySelector('.editor-buttons');

const originalButtonsHtml = editorButtons.innerHTML;
editorButtons.innerHTML = originalButtonsHtml + '<button class="btn btn-danger" id="deleteBtn" style="display:none;" onclick="deleteNote()">Delete</button>';

// Show/hide delete button
const noteEditor = document.getElementById('noteEditor');
const observer = new MutationObserver(() => {
  const deleteBtn = document.getElementById('deleteBtn');
  if (currentNoteId) {
    deleteBtn.style.display = 'block';
  } else {
    deleteBtn.style.display = 'none';
  }
});

observer.observe(noteEditor, { style: true, display: true });

// Add share and delete buttons directly in the editor buttons
document.addEventListener('DOMContentLoaded', () => {
  const editorButtons = document.querySelector('.editor-buttons');
  editorButtons.innerHTML += `
    <button class="btn share-btn" id="shareBtn" style="display:none;" onclick="showShareModal()">Share</button>
    <button class="btn delete-btn" id="deleteBtn" style="display:none;" onclick="deleteNote()">Delete</button>
  `;

  // Update button visibility when note is opened/closed
  setInterval(() => {
    const deleteBtn = document.getElementById('deleteBtn');
    const shareBtn = document.getElementById('shareBtn');
    const editor = document.getElementById('noteEditor');
    if (editor.style.display === 'flex' && currentNoteId) {
      deleteBtn.style.display = 'block';
      shareBtn.style.display = 'block';
    } else {
      deleteBtn.style.display = 'none';
      shareBtn.style.display = 'none';
    }
  }, 100);
});

async function showShareModal() {
  const modal = document.getElementById('shareModal');
  const modalContent = document.getElementById('shareModalContent');

  modal.style.display = 'flex';
  modal.classList.add('show');
  modalContent.innerHTML = '<p>Generating share link...</p>';

  try {
    const response = await fetch(`/api/notes/${currentNoteId}/share`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${getToken()}` }
    });

    if (response.status === 201) {
      const data = await response.json();
      const shareUrl = `${window.location.origin}/view.html?share=${data.share_token}`;
      modalContent.innerHTML = `
        <p>Share this link with anyone:</p>
        <input type="text" value="${shareUrl}" readonly>
        <button class="btn btn-primary" onclick="copyShareLinkFromModal('${shareUrl}')">Copy Link</button>
      `;
    }
  } catch (err) {
    modalContent.innerHTML = '<p>Error generating share link</p>';
  }
}

function copyShareLinkFromModal(url) {
  navigator.clipboard.writeText(url).then(() => {
    const btn = event.target;
    const originalText = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => {
      btn.textContent = originalText;
    }, 2000);
  });
}

function closeShareModal() {
  const modal = document.getElementById('shareModal');
  modal.style.display = 'none';
  modal.classList.remove('show');
}

// Close modal when clicking outside
document.addEventListener('click', (e) => {
  const modal = document.getElementById('shareModal');
  if (e.target === modal) {
    closeShareModal();
  }
});

// Load notes on page load
loadNotes();
setInterval(loadNotes, 30000);
