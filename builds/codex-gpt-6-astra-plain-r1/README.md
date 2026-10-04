# NoteShare

A small private notebook with email/password accounts, a responsive web interface, and a JSON API. Uses Python's standard library and SQLite; no third-party server packages are needed.

## Start

Requires Python 3.9 or newer, with SQLite and OpenSSL support (standard Python installations include both).

```sh
./start.sh
```

Open **http://localhost:3000**. To use a different port:

```sh
PORT=9093 ./start.sh
```

The script uses `PORT` when set, works from any working directory, and starts the server on all network interfaces. Stop with Ctrl+C. Run the same command to restart.

## Use

Choose **Create account**, enter an email and a password of at least eight characters, and start writing. Click **Save note** to save your changes. Notes are private until you select **Share**. Copy the link to let a friend read that one note without signing in.

Shared pages display the latest saved version. Creating another link replaces the old one. **Turn off sharing** revokes the link, and deleting a note also invalidates its link. Switching notes or leaving the page prompts you if changes are unsaved. Sessions stay in the current browser tab and last up to 30 days; logging out revokes that session.

## Storage

Accounts, password hashes, sessions, notes, and share-link hashes are stored in `data/noteshare.sqlite3`, alongside SQLite's journal files. The folder is created automatically beside `app.py`. Data survives restarts. To back up, stop the server and copy the entire `data` folder; restore it in the same location. Do not delete this folder unless you want to erase all accounts and notes.

## API

Send JSON request bodies with `Content-Type: application/json`. For private endpoints, send `Authorization: Bearer <token>`. Signup, login, and shared-note reads do not require authentication.

| Method | Path | Body / result |
| --- | --- | --- |
| POST | `/api/signup` | `{ "email": "you@example.com", "password": "your-password" }` → 201, `{ "email": "you@example.com" }` |
| POST | `/api/login` | Same credentials → 200, `{ "token": "..." }` |
| GET | `/api/notes` | 200, array of your notes, newest updates first |
| POST | `/api/notes` | `{ "title": "An idea", "body": "Write it down." }` → 201, created note |
| GET | `/api/notes/<id>` | 200, your note |
| PUT | `/api/notes/<id>` | `{ "title": "Updated title", "body": "Updated body" }` → 200, updated note |
| DELETE | `/api/notes/<id>` | 204, no body |
| POST | `/api/notes/<id>/share` | 200, `{ "share_token": "..." }`; replaces any previous link |
| GET | `/api/shared/<share_token>` | 200, shared note; no login needed |
| DELETE | `/api/notes/<id>/share` | 204; revokes sharing |
| POST | `/api/logout` | 204; revokes the current login token |

A private note has this shape:

```json
{
  "id": "opaque-note-id",
  "title": "An idea",
  "body": "Write it down.",
  "created_at": "2026-10-04T12:00:00Z",
  "updated_at": "2026-10-04T12:00:00Z",
  "shared": false
}
```

Public responses omit `shared`. The human-readable share link is `/shared/<share_token>`. Titles must contain 1–200 characters and bodies can contain up to 100,000 characters, including empty text. PUT requires both fields. Emails are case-insensitive. Passwords accept 8–256 characters. Errors are JSON: `{ "error": "Readable explanation" }`, with 400 for invalid input, 401 for authentication failures, 404 for unavailable notes, 409 for an existing email, and 429 for excessive authentication attempts.

## Checks

```sh
python3 -m unittest -v
```

Tests use temporary copies of the app, leaving your real data untouched. They cover signup/login, validation, CRUD, access isolation between accounts, public reads, link rotation and revocation, logout, and storage/session persistence after restarting.

## Hosting

For use beyond your own machine, serve it through an HTTPS reverse proxy so passwords, bearer tokens, and share links are encrypted in transit. This is a small single-server application, with hashed passwords (scrypt), cryptographically random tokens stored as hashes, parameterized SQL, ownership checks, and basic in-memory authentication rate limiting. It does not include email verification or password recovery. Native phone clients can use the API directly; browser apps on another origin would need an explicit CORS policy.
