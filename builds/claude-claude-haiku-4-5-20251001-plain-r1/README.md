# NoteShare

A simple note-sharing web app where you can create private notes and share them with a link.

## Features

- 📝 Create, edit, and delete notes
- 🔐 User authentication with email and password
- 🔗 Generate share links for individual notes (public access, no login required)
- 📱 JSON API for building apps (phone apps, etc.)
- 💾 Data persists in the folder (uses SQLite)

## Quick Start

### 1. Start the Server

```bash
./start.sh
```

Or with a custom port:

```bash
PORT=8080 ./start.sh
```

The server will:
- Install dependencies (npm install)
- Create the database (noteshare.db)
- Start the server on the port you specified (default: 3000)

### 2. Open in Your Browser

Once the server is running, open your browser to:

```
http://localhost:3000
```

### 3. Create an Account

- Sign up with your email and password
- Start creating notes
- Share notes with anyone using the share link

## Using the Web App

1. **Sign Up**: Create an account with your email and password
2. **Write Notes**: Click "New Note" to create a note with a title and body
3. **Edit Notes**: Click on a note in the list to edit it
4. **Delete Notes**: Click "Delete" while editing a note
5. **Share Notes**: Click "Share" to generate a public link anyone can view

## JSON API

All requests (except signup, login, and shared note viewing) require authentication using a JWT token in the `Authorization` header.

### Authentication

**POST /api/signup**
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**POST /api/login**
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

Returns:
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

### Notes API

All requests below require: `Authorization: Bearer <token>`

**GET /api/notes**
- List all your notes

**POST /api/notes**
```json
{
  "title": "My Note",
  "body": "Note content"
}
```

**GET /api/notes/<id>**
- Get a specific note

**PUT /api/notes/<id>**
```json
{
  "title": "Updated Title",
  "body": "Updated content"
}
```

**DELETE /api/notes/<id>**
- Delete a note

### Sharing API

**POST /api/notes/<id>/share**
- Generate a share link for a note
- Returns: `{"share_token": "..."}`

**GET /api/shared/<share_token>**
- View a shared note (no authentication required)

## Data Storage

All data is stored in `noteshare.db` in the same folder as the app. This file is created automatically when the server starts and persists between restarts.

## File Structure

```
.
├── start.sh           # Startup script
├── server.js          # Main server
├── db.js              # Database setup
├── package.json       # Dependencies
├── noteshare.db       # Database (created at runtime)
└── public/
    ├── index.html     # Login/signup page
    ├── notes.html     # Notes interface
    ├── view.html      # Shared note viewer
    ├── style.css      # Styling
    └── script.js      # Frontend logic
```

## Environment Variables

- `PORT` - Port to run the server on (default: 3000)

## Stopping the Server

Press `Ctrl+C` in the terminal where the server is running.

---

That's it! You now have a fully functional note-sharing app. Share away! 🚀
