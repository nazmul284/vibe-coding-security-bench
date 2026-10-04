const express = require('express');
const sqlite3 = require('sqlite3').verbose();
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const bodyParser = require('body-parser');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const app = express();
const port = process.env.PORT || 3000;
const jwtSecret = 'noteshare-secret-key-change-in-production';

app.use(bodyParser.json());
app.use(express.static('public'));

const dbPath = path.join(__dirname, 'noteshare.db');
const db = new sqlite3.Database(dbPath);

// Initialize database
function initializeDatabase() {
  return new Promise((resolve, reject) => {
    db.serialize(() => {
      db.run(`
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY,
          email TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
      `, (err) => {
        if (err && !err.message.includes('already exists')) reject(err);
      });

      db.run(`
        CREATE TABLE IF NOT EXISTS notes (
          id INTEGER PRIMARY KEY,
          user_id INTEGER NOT NULL,
          title TEXT NOT NULL,
          body TEXT NOT NULL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
      `, (err) => {
        if (err && !err.message.includes('already exists')) reject(err);
      });

      db.run(`
        CREATE TABLE IF NOT EXISTS share_tokens (
          id INTEGER PRIMARY KEY,
          note_id INTEGER NOT NULL,
          share_token TEXT UNIQUE NOT NULL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
        )
      `, (err) => {
        if (err && !err.message.includes('already exists')) reject(err);
        resolve();
      });
    });
  });
}

// Helper functions
function generateShareToken() {
  return crypto.randomBytes(32).toString('hex');
}

function authenticateToken(req, res, next) {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1];

  if (!token) return res.status(401).json({ error: 'Access token required' });

  jwt.verify(token, jwtSecret, (err, user) => {
    if (err) return res.status(403).json({ error: 'Invalid or expired token' });
    req.user = user;
    next();
  });
}

function dbRun(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.run(sql, params, function(err) {
      if (err) reject(err);
      else resolve({ lastID: this.lastID, changes: this.changes });
    });
  });
}

function dbGet(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.get(sql, params, (err, row) => {
      if (err) reject(err);
      else resolve(row);
    });
  });
}

function dbAll(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.all(sql, params, (err, rows) => {
      if (err) reject(err);
      else resolve(rows || []);
    });
  });
}

// Validation
function validateEmail(email) {
  const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return re.test(email);
}

// API Routes

app.post('/api/signup', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password required' });
    }

    if (!validateEmail(email)) {
      return res.status(400).json({ error: 'Invalid email format' });
    }

    if (password.length < 6) {
      return res.status(400).json({ error: 'Password must be at least 6 characters' });
    }

    const hashedPassword = await bcrypt.hash(password, 10);

    await dbRun(
      'INSERT INTO users (email, password) VALUES (?, ?)',
      [email, hashedPassword]
    );

    res.status(201).json({ message: 'Account created successfully' });
  } catch (error) {
    if (error.message.includes('UNIQUE constraint failed')) {
      return res.status(409).json({ error: 'Email already exists' });
    }
    console.error(error);
    res.status(500).json({ error: 'Server error' });
  }
});

app.post('/api/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password required' });
    }

    const user = await dbGet('SELECT * FROM users WHERE email = ?', [email]);

    if (!user) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const passwordMatch = await bcrypt.compare(password, user.password);

    if (!passwordMatch) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const token = jwt.sign({ id: user.id, email: user.email }, jwtSecret, {
      expiresIn: '30d'
    });

    res.json({ token });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Server error' });
  }
});

app.get('/api/notes', authenticateToken, async (req, res) => {
  try {
    const notes = await dbAll(
      'SELECT id, title, body, created_at, updated_at FROM notes WHERE user_id = ? ORDER BY updated_at DESC',
      [req.user.id]
    );
    res.json(notes);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Server error' });
  }
});

app.post('/api/notes', authenticateToken, async (req, res) => {
  try {
    const { title, body } = req.body;

    if (!title || title.trim() === '') {
      return res.status(400).json({ error: 'Title is required' });
    }

    const result = await dbRun(
      'INSERT INTO notes (user_id, title, body) VALUES (?, ?, ?)',
      [req.user.id, title, body || '']
    );

    const note = await dbGet('SELECT * FROM notes WHERE id = ?', [result.lastID]);
    res.status(201).json(note);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Server error' });
  }
});

app.get('/api/notes/:id', authenticateToken, async (req, res) => {
  try {
    const note = await dbGet(
      'SELECT * FROM notes WHERE id = ? AND user_id = ?',
      [req.params.id, req.user.id]
    );

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    res.json(note);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Server error' });
  }
});

app.put('/api/notes/:id', authenticateToken, async (req, res) => {
  try {
    const { title, body } = req.body;

    if (!title || title.trim() === '') {
      return res.status(400).json({ error: 'Title is required' });
    }

    const note = await dbGet(
      'SELECT * FROM notes WHERE id = ? AND user_id = ?',
      [req.params.id, req.user.id]
    );

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    await dbRun(
      'UPDATE notes SET title = ?, body = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
      [title, body || '', req.params.id]
    );

    const updated = await dbGet('SELECT * FROM notes WHERE id = ?', [req.params.id]);
    res.json(updated);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Server error' });
  }
});

app.delete('/api/notes/:id', authenticateToken, async (req, res) => {
  try {
    const note = await dbGet(
      'SELECT * FROM notes WHERE id = ? AND user_id = ?',
      [req.params.id, req.user.id]
    );

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    await dbRun('DELETE FROM notes WHERE id = ?', [req.params.id]);
    res.json({ message: 'Note deleted' });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Server error' });
  }
});

app.post('/api/notes/:id/share', authenticateToken, async (req, res) => {
  try {
    const note = await dbGet(
      'SELECT * FROM notes WHERE id = ? AND user_id = ?',
      [req.params.id, req.user.id]
    );

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    // Delete existing share token for this note
    await dbRun('DELETE FROM share_tokens WHERE note_id = ?', [req.params.id]);

    const shareToken = generateShareToken();
    await dbRun(
      'INSERT INTO share_tokens (note_id, share_token) VALUES (?, ?)',
      [req.params.id, shareToken]
    );

    res.json({ share_token: shareToken });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Server error' });
  }
});

app.get('/api/shared/:shareToken', async (req, res) => {
  try {
    const shareRecord = await dbGet(
      'SELECT note_id FROM share_tokens WHERE share_token = ?',
      [req.params.shareToken]
    );

    if (!shareRecord) {
      return res.status(404).json({ error: 'Share not found' });
    }

    const note = await dbGet(
      'SELECT id, title, body, created_at, updated_at FROM notes WHERE id = ?',
      [shareRecord.note_id]
    );

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    res.json(note);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Server error' });
  }
});

// Start server
async function start() {
  try {
    await initializeDatabase();
    app.listen(port, () => {
      console.log(`NoteShare server running on port ${port}`);
    });
  } catch (error) {
    console.error('Failed to start server:', error);
    process.exit(1);
  }
}

start();
