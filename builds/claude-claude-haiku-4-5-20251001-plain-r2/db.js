const sqlite3 = require('sqlite3').verbose();
const path = require('path');

const dbPath = path.join(__dirname, 'notes.db');
const db = new sqlite3.Database(dbPath);

db.serialize(() => {
  db.run(`CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
  )`);

  db.run(`CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
  )`);

  db.run(`CREATE TABLE IF NOT EXISTS share_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER NOT NULL,
    token TEXT UNIQUE NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (note_id) REFERENCES notes(id)
  )`);
});

const queries = {
  createUser: (email, hashedPassword) => {
    return new Promise((resolve, reject) => {
      db.run(
        'INSERT INTO users (email, password) VALUES (?, ?)',
        [email, hashedPassword],
        function(err) {
          if (err) reject(err);
          else resolve(this.lastID);
        }
      );
    });
  },

  getUserByEmail: (email) => {
    return new Promise((resolve, reject) => {
      db.get(
        'SELECT * FROM users WHERE email = ?',
        [email],
        (err, row) => {
          if (err) reject(err);
          else resolve(row);
        }
      );
    });
  },

  getUserById: (id) => {
    return new Promise((resolve, reject) => {
      db.get(
        'SELECT id, email FROM users WHERE id = ?',
        [id],
        (err, row) => {
          if (err) reject(err);
          else resolve(row);
        }
      );
    });
  },

  createNote: (userId, title, body) => {
    return new Promise((resolve, reject) => {
      db.run(
        'INSERT INTO notes (user_id, title, body) VALUES (?, ?, ?)',
        [userId, title, body],
        function(err) {
          if (err) reject(err);
          else resolve(this.lastID);
        }
      );
    });
  },

  getNoteById: (id) => {
    return new Promise((resolve, reject) => {
      db.get(
        'SELECT * FROM notes WHERE id = ?',
        [id],
        (err, row) => {
          if (err) reject(err);
          else resolve(row);
        }
      );
    });
  },

  getUserNotes: (userId) => {
    return new Promise((resolve, reject) => {
      db.all(
        'SELECT id, title, body, created_at, updated_at FROM notes WHERE user_id = ? ORDER BY updated_at DESC',
        [userId],
        (err, rows) => {
          if (err) reject(err);
          else resolve(rows);
        }
      );
    });
  },

  updateNote: (noteId, userId, title, body) => {
    return new Promise((resolve, reject) => {
      db.run(
        'UPDATE notes SET title = ?, body = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?',
        [title, body, noteId, userId],
        function(err) {
          if (err) reject(err);
          else resolve(this.changes);
        }
      );
    });
  },

  deleteNote: (noteId, userId) => {
    return new Promise((resolve, reject) => {
      db.run(
        'DELETE FROM notes WHERE id = ? AND user_id = ?',
        [noteId, userId],
        function(err) {
          if (err) reject(err);
          else resolve(this.changes);
        }
      );
    });
  },

  createShareToken: (noteId, token) => {
    return new Promise((resolve, reject) => {
      db.run(
        'INSERT INTO share_tokens (note_id, token) VALUES (?, ?)',
        [noteId, token],
        function(err) {
          if (err) reject(err);
          else resolve(token);
        }
      );
    });
  },

  getSharedNote: (shareToken) => {
    return new Promise((resolve, reject) => {
      db.get(
        `SELECT n.id, n.title, n.body, n.created_at, n.updated_at
         FROM notes n
         JOIN share_tokens st ON n.id = st.note_id
         WHERE st.token = ?`,
        [shareToken],
        (err, row) => {
          if (err) reject(err);
          else resolve(row);
        }
      );
    });
  },

  getShareToken: (noteId) => {
    return new Promise((resolve, reject) => {
      db.get(
        'SELECT token FROM share_tokens WHERE note_id = ? LIMIT 1',
        [noteId],
        (err, row) => {
          if (err) reject(err);
          else resolve(row?.token);
        }
      );
    });
  }
};

module.exports = { db, queries };
