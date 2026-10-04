#!/bin/bash

set -e

# Default port
PORT=${PORT:-3000}

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
  echo "Installing dependencies..."
  npm install
fi

# Handle shared note routing
# Create a wrapper server that handles the shared note route
cat > _server_wrapper.js << 'WRAPPER_EOF'
const express = require('express');
const bodyParser = require('body-parser');
const cors = require('cors');
const path = require('path');
const auth = require('./auth');
const { queries } = require('./db');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(bodyParser.json());
app.use(cors());
app.use(express.static('public'));

// Middleware to verify JWT token
const authenticateToken = (req, res, next) => {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1];

  if (!token) {
    return res.status(401).json({ error: 'No token provided' });
  }

  const decoded = auth.verifyToken(token);
  if (!decoded) {
    return res.status(401).json({ error: 'Invalid token' });
  }

  req.userId = decoded.userId;
  next();
};

// Signup
app.post('/api/signup', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password required' });
    }

    const existingUser = await queries.getUserByEmail(email);
    if (existingUser) {
      return res.status(400).json({ error: 'Email already registered' });
    }

    const hashedPassword = await auth.hashPassword(password);
    const userId = await queries.createUser(email, hashedPassword);

    res.json({ id: userId, email });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Signup failed' });
  }
});

// Login
app.post('/api/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password required' });
    }

    const user = await queries.getUserByEmail(email);
    if (!user) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const isValid = await auth.comparePassword(password, user.password);
    if (!isValid) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const token = auth.createToken(user.id);
    res.json({ token });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Login failed' });
  }
});

// Get all notes for user
app.get('/api/notes', authenticateToken, async (req, res) => {
  try {
    const notes = await queries.getUserNotes(req.userId);
    res.json(notes);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to fetch notes' });
  }
});

// Create note
app.post('/api/notes', authenticateToken, async (req, res) => {
  try {
    const { title, body } = req.body;

    if (!title) {
      return res.status(400).json({ error: 'Title required' });
    }

    const noteId = await queries.createNote(req.userId, title, body || '');
    const note = await queries.getNoteById(noteId);

    res.status(201).json(note);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to create note' });
  }
});

// Get single note
app.get('/api/notes/:id', authenticateToken, async (req, res) => {
  try {
    const note = await queries.getNoteById(req.params.id);

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    if (note.user_id !== req.userId) {
      return res.status(403).json({ error: 'Access denied' });
    }

    res.json(note);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to fetch note' });
  }
});

// Update note
app.put('/api/notes/:id', authenticateToken, async (req, res) => {
  try {
    const { title, body } = req.body;

    const note = await queries.getNoteById(req.params.id);
    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    if (note.user_id !== req.userId) {
      return res.status(403).json({ error: 'Access denied' });
    }

    await queries.updateNote(req.params.id, req.userId, title || note.title, body !== undefined ? body : note.body);
    const updated = await queries.getNoteById(req.params.id);

    res.json(updated);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to update note' });
  }
});

// Delete note
app.delete('/api/notes/:id', authenticateToken, async (req, res) => {
  try {
    const note = await queries.getNoteById(req.params.id);

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    if (note.user_id !== req.userId) {
      return res.status(403).json({ error: 'Access denied' });
    }

    await queries.deleteNote(req.params.id, req.userId);
    res.json({ success: true });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to delete note' });
  }
});

// Create share token
app.post('/api/notes/:id/share', authenticateToken, async (req, res) => {
  try {
    const note = await queries.getNoteById(req.params.id);

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    if (note.user_id !== req.userId) {
      return res.status(403).json({ error: 'Access denied' });
    }

    let shareToken = await queries.getShareToken(req.params.id);
    if (!shareToken) {
      shareToken = auth.generateShareToken();
      await queries.createShareToken(req.params.id, shareToken);
    }

    res.json({ share_token: shareToken });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to create share token' });
  }
});

// Get shared note (no auth required)
app.get('/api/shared/:share_token', async (req, res) => {
  try {
    const note = await queries.getSharedNote(req.params.share_token);

    if (!note) {
      return res.status(404).json({ error: 'Shared note not found' });
    }

    res.json(note);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Failed to fetch shared note' });
  }
});

// Handle shared note routes - must be last
app.get('/shared/:share_token', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`NoteShare server running on http://localhost:${PORT}`);
});
WRAPPER_EOF

echo "Starting NoteShare on port $PORT..."
PORT=$PORT node _server_wrapper.js
