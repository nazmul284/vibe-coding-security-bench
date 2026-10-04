const express = require('express');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const bodyParser = require('body-parser');
const { initDb, run, get, all } = require('./db');
const path = require('path');
const crypto = require('crypto');

const app = express();
const port = process.env.PORT || 3000;
const jwtSecret = 'your-secret-key-change-in-production';

app.use(bodyParser.json());
app.use(express.static(path.join(__dirname, 'public')));

// Middleware to verify JWT token
function authenticateToken(req, res, next) {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1];

  if (!token) return res.status(401).json({ error: 'No token provided' });

  jwt.verify(token, jwtSecret, (err, user) => {
    if (err) return res.status(403).json({ error: 'Invalid token' });
    req.user = user;
    next();
  });
}

// POST /api/signup
app.post('/api/signup', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password required' });
    }

    const hashedPassword = await bcrypt.hash(password, 10);
    await run('INSERT INTO users (email, password) VALUES (?, ?)', [email, hashedPassword]);

    res.status(201).json({ message: 'User created successfully' });
  } catch (err) {
    if (err.message.includes('UNIQUE constraint failed')) {
      res.status(409).json({ error: 'Email already exists' });
    } else {
      res.status(500).json({ error: 'Internal server error' });
    }
  }
});

// POST /api/login
app.post('/api/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password required' });
    }

    const user = await get('SELECT * FROM users WHERE email = ?', [email]);

    if (!user) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const validPassword = await bcrypt.compare(password, user.password);

    if (!validPassword) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const token = jwt.sign({ userId: user.id, email: user.email }, jwtSecret, { expiresIn: '30d' });
    res.json({ token });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// GET /api/notes - List user's notes
app.get('/api/notes', authenticateToken, async (req, res) => {
  try {
    const notes = await all('SELECT id, title, body, created_at, updated_at FROM notes WHERE user_id = ? ORDER BY updated_at DESC', [req.user.userId]);
    res.json(notes);
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// POST /api/notes - Create a note
app.post('/api/notes', authenticateToken, async (req, res) => {
  try {
    const { title, body } = req.body;

    if (!title || body === undefined) {
      return res.status(400).json({ error: 'Title and body required' });
    }

    const result = await run('INSERT INTO notes (user_id, title, body) VALUES (?, ?, ?)', [req.user.userId, title, body]);
    const note = await get('SELECT id, title, body, created_at, updated_at FROM notes WHERE id = ?', [result.lastID]);

    res.status(201).json(note);
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// GET /api/notes/<id> - Get a specific note
app.get('/api/notes/:id', authenticateToken, async (req, res) => {
  try {
    const note = await get('SELECT id, title, body, created_at, updated_at FROM notes WHERE id = ? AND user_id = ?', [req.params.id, req.user.userId]);

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    res.json(note);
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// PUT /api/notes/<id> - Update a note
app.put('/api/notes/:id', authenticateToken, async (req, res) => {
  try {
    const { title, body } = req.body;

    if (!title || body === undefined) {
      return res.status(400).json({ error: 'Title and body required' });
    }

    const note = await get('SELECT id FROM notes WHERE id = ? AND user_id = ?', [req.params.id, req.user.userId]);

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    await run('UPDATE notes SET title = ?, body = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', [title, body, req.params.id]);
    const updated = await get('SELECT id, title, body, created_at, updated_at FROM notes WHERE id = ?', [req.params.id]);

    res.json(updated);
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// DELETE /api/notes/<id> - Delete a note
app.delete('/api/notes/:id', authenticateToken, async (req, res) => {
  try {
    const note = await get('SELECT id FROM notes WHERE id = ? AND user_id = ?', [req.params.id, req.user.userId]);

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    await run('DELETE FROM notes WHERE id = ?', [req.params.id]);
    res.json({ message: 'Note deleted' });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// POST /api/notes/<id>/share - Create a share link
app.post('/api/notes/:id/share', authenticateToken, async (req, res) => {
  try {
    const note = await get('SELECT id FROM notes WHERE id = ? AND user_id = ?', [req.params.id, req.user.userId]);

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    const shareToken = crypto.randomBytes(32).toString('hex');
    await run('INSERT INTO shares (note_id, share_token) VALUES (?, ?)', [req.params.id, shareToken]);

    res.json({ share_token: shareToken });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// GET /api/shared/<share_token> - Get a shared note (no auth required)
app.get('/api/shared/:shareToken', async (req, res) => {
  try {
    const share = await get('SELECT note_id FROM shares WHERE share_token = ?', [req.params.shareToken]);

    if (!share) {
      return res.status(404).json({ error: 'Share not found' });
    }

    const note = await get('SELECT id, title, body, created_at, updated_at FROM notes WHERE id = ?', [share.note_id]);

    if (!note) {
      return res.status(404).json({ error: 'Note not found' });
    }

    res.json(note);
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Initialize database and start server
initDb().then(() => {
  app.listen(port, () => {
    console.log(`NoteShare server running at http://localhost:${port}`);
  });
}).catch(err => {
  console.error('Failed to initialize database:', err);
  process.exit(1);
});
