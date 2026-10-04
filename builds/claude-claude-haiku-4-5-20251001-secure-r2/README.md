# NoteShare

A secure note-taking app with sharing capabilities. Create private notes and share them with others via secure links.

## Features

- 🔐 **Secure Authentication** - Sign up and log in with email and password
- 📝 **Create & Edit Notes** - Write notes with titles and content
- 🔒 **Private by Default** - All notes are private to your account
- 🔗 **Share Notes** - Generate secure share links for individual notes
- 📱 **Mobile-Ready API** - Full JSON API for building mobile apps
- 💾 **Local Storage** - All data stored locally in your folder

## Quick Start

### Prerequisites

- Node.js 16 or higher (check with `node --version`)

### Installation & Running

The simplest way to get started:

```bash
./start.sh
```

This script will:
1. Install dependencies (if needed)
2. Start the server on port 3000

Or specify a different port:

```bash
PORT=8080 ./start.sh
```

Then open your browser to **http://localhost:3000**

## Using the App

### Web Interface

1. **Sign Up** - Create an account with your email and password
2. **Create Notes** - Click "New Note" and start writing
3. **Edit Notes** - Click the "Edit" button to modify a note
4. **Share Notes** - Click "Share" to generate a link you can send to friends
5. **View Shared Notes** - Share the link and anyone can view that note without logging in

### API

All API requests (except signup, login, and viewing shared notes) require:

```
Authorization: Bearer <token>
```

#### Authentication

**Sign Up**
```bash
curl -X POST http://localhost:3000/api/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password123"}'
```

Response:
```json
{
  "token": "eyJhb...",
  "userId": "uuid",
  "email": "user@example.com"
}
```

**Log In**
```bash
curl -X POST http://localhost:3000/api/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password123"}'
```

#### Notes

**List Your Notes**
```bash
curl http://localhost:3000/api/notes \
  -H "Authorization: Bearer <token>"
```

**Create a Note**
```bash
curl -X POST http://localhost:3000/api/notes \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"title":"My Note","body":"Note content"}'
```

**Get a Note**
```bash
curl http://localhost:3000/api/notes/<note-id> \
  -H "Authorization: Bearer <token>"
```

**Update a Note**
```bash
curl -X PUT http://localhost:3000/api/notes/<note-id> \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"title":"Updated Title","body":"Updated content"}'
```

**Delete a Note**
```bash
curl -X DELETE http://localhost:3000/api/notes/<note-id> \
  -H "Authorization: Bearer <token>"
```

#### Sharing

**Create a Share Link**
```bash
curl -X POST http://localhost:3000/api/notes/<note-id>/share \
  -H "Authorization: Bearer <token>"
```

Response:
```json
{
  "share_token": "uuid"
}
```

Share link: `http://localhost:3000?share=<share_token>`

**View a Shared Note** (no authentication required)
```bash
curl http://localhost:3000/api/shared/<share_token>
```

## Security Features

- 🔐 **Password Hashing** - Passwords are hashed with bcrypt
- 🔑 **JWT Tokens** - Secure token-based authentication
- 🛡️ **SQL Injection Prevention** - Parameterized database queries
- 📝 **Input Validation** - Email and password validation
- 🚫 **Private Notes** - No cross-user access to notes
- 🔗 **Secure Sharing** - UUIDs make share links impossible to guess

## File Storage

- All data is stored in `data.db` in this folder
- The database file will be created automatically on first run
- Back up `data.db` to preserve your notes

## Environment Variables

- `PORT` - Port to run the server on (default: 3000)
- `JWT_SECRET` - Secret for signing JWT tokens (default: 'change-this-secret-in-production')

⚠️ **Important for Production**: Change the `JWT_SECRET` before deploying to production.

## Troubleshooting

**"Node.js is not installed"**
- Install Node.js from https://nodejs.org/ (version 16 or higher)

**Port already in use**
- Kill the process: `pkill -f "node server.js"`
- Or use a different port: `PORT=8080 ./start.sh`

**Database locked**
- Make sure only one instance of the app is running
- Delete `data.db` and restart to reset (data will be lost)

## Tech Stack

- **Server**: Node.js + Express
- **Database**: SQLite
- **Authentication**: JWT + bcryptjs
- **Frontend**: Vanilla HTML/CSS/JavaScript
- **IDs**: UUIDs for all entities

## License

MIT
