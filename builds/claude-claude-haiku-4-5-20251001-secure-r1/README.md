# NoteShare

A simple, secure note-sharing app. Users can create private notes, edit them, and share individual notes via a link without requiring the recipient to have an account.

## Features

- **User Accounts**: Sign up with email and password
- **Note Management**: Create, read, update, and delete private notes
- **Share Notes**: Generate shareable links for individual notes
- **No Account Required to View**: Friends can view shared notes without signing up
- **Web UI**: Clean, simple interface for managing notes
- **JSON API**: Full API for integrating with mobile apps or other clients
- **Secure**: Password hashing with bcryptjs, JWT authentication, SQL injection prevention

## Quick Start

### Installation and Running

```bash
./start.sh
```

This will install dependencies and start the server on the port specified in the `PORT` environment variable (defaults to 3000).

```bash
PORT=8000 ./start.sh
```

Then open your browser to `http://localhost:3000` (or your chosen port).

### Data Storage

The app stores all data in a `noteshare.db` file in the app directory. This file persists between restarts, so your data won't be lost.

## Web Interface

1. **Sign Up**: Create an account with your email and a password (at least 6 characters)
2. **Log In**: Enter your credentials
3. **Create Notes**: Click "New Note" to create a note with a title and body
4. **View Notes**: Click on a note in the list to view it
5. **Edit Notes**: Click "Edit" to modify the title or body
6. **Delete Notes**: Click "Delete" to remove a note (can't be undone)
7. **Share Notes**: Click "Share" to create a link. Copy the link and send it to anyone
8. **View Shared Notes**: Anyone with a share link can view the note without an account

## JSON API

All API endpoints use JSON. The base URL is `/api`.

### Authentication

All endpoints except signup, login, and shared notes require a JWT token:

```
Authorization: Bearer <token>
```

### Endpoints

#### Signup
Create a new account.

```
POST /api/signup
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123"
}
```

Response:
```json
{
  "message": "Account created successfully"
}
```

#### Login
Get an authentication token.

```
POST /api/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123"
}
```

Response:
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

#### Get All Notes
List all notes for the authenticated user.

```
GET /api/notes
Authorization: Bearer <token>
```

Response:
```json
[
  {
    "id": 1,
    "title": "My Note",
    "body": "Note content here",
    "created_at": "2026-10-04 12:00:00",
    "updated_at": "2026-10-04 12:00:00"
  }
]
```

#### Create Note
Create a new note.

```
POST /api/notes
Authorization: Bearer <token>
Content-Type: application/json

{
  "title": "My Note",
  "body": "Note content here"
}
```

Response: The created note with its ID.

#### Get Note
Retrieve a single note.

```
GET /api/notes/<id>
Authorization: Bearer <token>
```

Response: The note object.

#### Update Note
Modify an existing note.

```
PUT /api/notes/<id>
Authorization: Bearer <token>
Content-Type: application/json

{
  "title": "Updated Title",
  "body": "Updated content"
}
```

Response: The updated note.

#### Delete Note
Remove a note (permanent).

```
DELETE /api/notes/<id>
Authorization: Bearer <token>
```

Response:
```json
{
  "message": "Note deleted"
}
```

#### Share Note
Create a shareable link for a note.

```
POST /api/notes/<id>/share
Authorization: Bearer <token>
```

Response:
```json
{
  "share_token": "22a5fb9a63001e89cb4995cafb2f43ed84a8ae922de7663030cc53717104496a"
}
```

The shareable URL is: `http://your-domain.com?shared=<share_token>`

#### View Shared Note
View a note via a share link (no authentication needed).

```
GET /api/shared/<share_token>
```

Response: The note object (without user info).

## Security Notes

- **Passwords**: Hashed with bcryptjs, never stored in plaintext
- **Tokens**: JWT tokens expire after 30 days
- **Share Links**: Use cryptographically random tokens (256-bit)
- **SQL Injection**: All database queries use parameterized statements
- **Input Validation**: Email format and password length are validated
- **Private by Default**: Notes are only accessible to their owner (except via share links)

## Technical Stack

- **Backend**: Node.js + Express
- **Database**: SQLite3
- **Authentication**: JWT (jsonwebtoken)
- **Password Hashing**: bcryptjs
- **Frontend**: Plain HTML, CSS, and JavaScript (no frameworks)

## File Structure

```
.
├── server.js           # Express server with all API endpoints
├── package.json        # Node.js dependencies
├── start.sh           # Startup script
├── public/
│   └── index.html     # Web UI
├── noteshare.db       # SQLite database (created on first run)
└── README.md          # This file
```

## Development

### Building a Phone App

The JSON API makes it easy to build mobile apps. Here's a basic workflow:

1. Call `POST /api/signup` to create an account
2. Call `POST /api/login` to get a token
3. Store the token securely (use device secure storage, not plain text)
4. Use the token in the `Authorization` header for all subsequent requests
5. Implement UI for creating, editing, and deleting notes
6. Generate share links with `POST /api/notes/<id>/share`

### Deployment

For production use:

1. Change the `jwtSecret` in `server.js` to a strong random string
2. Use HTTPS (the web and API should never run on HTTP)
3. Set up proper database backups
4. Consider adding rate limiting for signup/login endpoints
5. Add CORS headers if your API will be accessed from different domains

## License

Free to use and modify for any purpose.
