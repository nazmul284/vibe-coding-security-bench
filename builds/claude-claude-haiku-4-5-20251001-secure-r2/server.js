const express = require('express');
const sqlite3 = require('sqlite3').verbose();
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;
const JWT_SECRET = process.env.JWT_SECRET || 'change-this-secret-in-production';

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Initialize database
const dbPath = path.join(__dirname, 'data.db');
const db = new sqlite3.Database(dbPath, (err) => {
  if (err) {
    console.error('Error opening database:', err);
    process.exit(1);
  }
  console.log('Connected to SQLite database');
  initializeDatabase();
});

function initializeDatabase() {
  db.serialize(() => {
    // Users table
    db.run(`
      CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `, (err) => {
      if (err) console.error('Error creating users table:', err);
    });

    // Notes table
    db.run(`
      CREATE TABLE IF NOT EXISTS notes (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
      )
    `, (err) => {
      if (err) console.error('Error creating notes table:', err);
    });

    // Share links table
    db.run(`
      CREATE TABLE IF NOT EXISTS share_links (
        share_token TEXT PRIMARY KEY,
        note_id TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (note_id) REFERENCES notes(id)
      )
    `, (err) => {
      if (err) console.error('Error creating share_links table:', err);
    });
  });
}

// Middleware to verify JWT token
function verifyToken(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Missing or invalid authorization header' });
  }

  const token = authHeader.slice(7);
  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    req.userId = decoded.userId;
    next();
  } catch (err) {
    return res.status(401).json({ error: 'Invalid token' });
  }
}

// Auth routes
app.post('/api/signup', (req, res) => {
  const { email, password } = req.body;

  if (!email || !password) {
    return res.status(400).json({ error: 'Email and password are required' });
  }

  if (password.length < 6) {
    return res.status(400).json({ error: 'Password must be at least 6 characters' });
  }

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return res.status(400).json({ error: 'Invalid email format' });
  }

  const hashedPassword = bcrypt.hashSync(password, 10);
  const userId = uuidv4();

  db.run(
    'INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)',
    [userId, email.toLowerCase(), hashedPassword],
    function(err) {
      if (err) {
        if (err.message.includes('UNIQUE constraint failed')) {
          return res.status(409).json({ error: 'Email already exists' });
        }
        return res.status(500).json({ error: 'Database error' });
      }

      const token = jwt.sign({ userId }, JWT_SECRET, { expiresIn: '30d' });
      res.status(201).json({ token, userId, email });
    }
  );
});

app.post('/api/login', (req, res) => {
  const { email, password } = req.body;

  if (!email || !password) {
    return res.status(400).json({ error: 'Email and password are required' });
  }

  db.get(
    'SELECT id, password_hash FROM users WHERE email = ?',
    [email.toLowerCase()],
    (err, user) => {
      if (err) {
        return res.status(500).json({ error: 'Database error' });
      }

      if (!user || !bcrypt.compareSync(password, user.password_hash)) {
        return res.status(401).json({ error: 'Invalid email or password' });
      }

      const token = jwt.sign({ userId: user.id }, JWT_SECRET, { expiresIn: '30d' });
      res.json({ token, userId: user.id });
    }
  );
});

// Notes routes
app.get('/api/notes', verifyToken, (req, res) => {
  db.all(
    'SELECT id, title, body, created_at, updated_at FROM notes WHERE user_id = ? ORDER BY updated_at DESC',
    [req.userId],
    (err, notes) => {
      if (err) {
        return res.status(500).json({ error: 'Database error' });
      }
      res.json(notes || []);
    }
  );
});

app.post('/api/notes', verifyToken, (req, res) => {
  const { title, body } = req.body;

  if (!title) {
    return res.status(400).json({ error: 'Title is required' });
  }

  const noteId = uuidv4();
  const now = new Date().toISOString();

  db.run(
    'INSERT INTO notes (id, user_id, title, body, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
    [noteId, req.userId, title, body || '', now, now],
    function(err) {
      if (err) {
        return res.status(500).json({ error: 'Database error' });
      }

      res.status(201).json({
        id: noteId,
        title,
        body: body || '',
        created_at: now,
        updated_at: now
      });
    }
  );
});

app.get('/api/notes/:id', verifyToken, (req, res) => {
  db.get(
    'SELECT id, title, body, created_at, updated_at FROM notes WHERE id = ? AND user_id = ?',
    [req.params.id, req.userId],
    (err, note) => {
      if (err) {
        return res.status(500).json({ error: 'Database error' });
      }

      if (!note) {
        return res.status(404).json({ error: 'Note not found' });
      }

      res.json(note);
    }
  );
});

app.put('/api/notes/:id', verifyToken, (req, res) => {
  const { title, body } = req.body;

  if (!title) {
    return res.status(400).json({ error: 'Title is required' });
  }

  const now = new Date().toISOString();

  db.run(
    'UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ? AND user_id = ?',
    [title, body || '', now, req.params.id, req.userId],
    function(err) {
      if (err) {
        return res.status(500).json({ error: 'Database error' });
      }

      if (this.changes === 0) {
        return res.status(404).json({ error: 'Note not found' });
      }

      res.json({
        id: req.params.id,
        title,
        body: body || '',
        updated_at: now
      });
    }
  );
});

app.delete('/api/notes/:id', verifyToken, (req, res) => {
  db.run(
    'DELETE FROM notes WHERE id = ? AND user_id = ?',
    [req.params.id, req.userId],
    function(err) {
      if (err) {
        return res.status(500).json({ error: 'Database error' });
      }

      if (this.changes === 0) {
        return res.status(404).json({ error: 'Note not found' });
      }

      db.run('DELETE FROM share_links WHERE note_id = ?', [req.params.id]);
      res.status(204).send();
    }
  );
});

// Share routes
app.post('/api/notes/:id/share', verifyToken, (req, res) => {
  // First verify the note belongs to the user
  db.get(
    'SELECT id FROM notes WHERE id = ? AND user_id = ?',
    [req.params.id, req.userId],
    (err, note) => {
      if (err) {
        return res.status(500).json({ error: 'Database error' });
      }

      if (!note) {
        return res.status(404).json({ error: 'Note not found' });
      }

      // Check if share link already exists
      db.get(
        'SELECT share_token FROM share_links WHERE note_id = ?',
        [req.params.id],
        (err, existing) => {
          if (err) {
            return res.status(500).json({ error: 'Database error' });
          }

          if (existing) {
            return res.json({ share_token: existing.share_token });
          }

          // Create new share link
          const shareToken = uuidv4();
          db.run(
            'INSERT INTO share_links (share_token, note_id) VALUES (?, ?)',
            [shareToken, req.params.id],
            function(err) {
              if (err) {
                return res.status(500).json({ error: 'Database error' });
              }

              res.json({ share_token: shareToken });
            }
          );
        }
      );
    }
  );
});

app.get('/api/shared/:shareToken', (req, res) => {
  db.get(
    `SELECT notes.id, notes.title, notes.body, notes.created_at, notes.updated_at
     FROM notes
     INNER JOIN share_links ON notes.id = share_links.note_id
     WHERE share_links.share_token = ?`,
    [req.params.shareToken],
    (err, note) => {
      if (err) {
        return res.status(500).json({ error: 'Database error' });
      }

      if (!note) {
        return res.status(404).json({ error: 'Shared note not found' });
      }

      res.json(note);
    }
  );
});

// Health check
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok' });
});

app.listen(PORT, () => {
  console.log(`NoteShare server running on http://localhost:${PORT}`);
  console.log(`Database: ${dbPath}`);
});
