# NoteShare

A simple web app for sharing private notes with optional public share links.

## Features

- **User Accounts**: Sign up with email and password, secure login
- **Private Notes**: Create, edit, and delete notes that only you can see
- **Share Links**: Generate public links to share individual notes without requiring login
- **Simple UI**: Clean, intuitive web interface
- **JSON API**: Full REST API for building mobile apps or integrations

## Quick Start

```bash
./start.sh
```

The app will start on port 3000 (or the port specified by the `PORT` environment variable).

Then open http://localhost:3000 in your browser.

## Running on a Custom Port

```bash
PORT=8080 ./start.sh
```

## How to Use

1. **Sign Up**: Create an account with your email and a password
2. **Create Notes**: Click "New Note" and start writing
3. **Edit Notes**: Click a note to edit its title and body
4. **Share a Note**: Click "Share" on any note to get a public link you can send to anyone
5. **Delete Notes**: Click "Delete" to remove a note permanently
6. **Log Out**: Click "Logout" when done

## API Documentation

All API endpoints (except signup, login, and accessing shared notes) require an Authorization header:
```
Authorization: Bearer <token>
```

### Authentication

**Sign Up**
```
POST /api/signup
Content-Type: application/json

{"email": "user@example.com", "password": "password"}
```

**Login**
```
POST /api/login
Content-Type: application/json

{"email": "user@example.com", "password": "password"}
```

Returns: `{"token": "..."}`

### Notes

**List Your Notes**
```
GET /api/notes
Authorization: Bearer <token>
```

**Create a Note**
```
POST /api/notes
Authorization: Bearer <token>
Content-Type: application/json

{"title": "My Note", "body": "Note content"}
```

**Get a Note**
```
GET /api/notes/<id>
Authorization: Bearer <token>
```

**Update a Note**
```
PUT /api/notes/<id>
Authorization: Bearer <token>
Content-Type: application/json

{"title": "Updated Title", "body": "Updated content"}
```

**Delete a Note**
```
DELETE /api/notes/<id>
Authorization: Bearer <token>
```

**Create Share Link**
```
POST /api/notes/<id>/share
Authorization: Bearer <token>
```

Returns: `{"share_token": "..."}`

**View Shared Note (No Login Required)**
```
GET /api/shared/<share_token>
```

## Data Storage

All data is stored in a SQLite database file (`notes.db`) in the application directory. It persists across server restarts.

## Files

- `server.js` - Main Express server with API endpoints
- `db.js` - SQLite database setup and query functions
- `auth.js` - Password hashing and JWT token utilities
- `public/index.html` - Web interface
- `public/style.css` - Styling
- `public/app.js` - Frontend JavaScript
- `package.json` - Node.js dependencies
- `start.sh` - Setup and startup script

## Security Notes

- Passwords are hashed with bcrypt
- Login tokens use JWT and expire after 30 days
- Notes are protected by user ID checks
- Share tokens are random and unique per note
- CORS is enabled for API access from different origins
