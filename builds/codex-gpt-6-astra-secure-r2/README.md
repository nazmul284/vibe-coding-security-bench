# NoteShare

A small private notebook with email/password accounts, a browser interface, and a JSON API.

## Start

Install Python 3.10 or newer, then run from this folder:

```sh
PORT=8000 ./start.sh
```

Open http://localhost:8000. The script installs pinned dependencies into `.venv` and starts Gunicorn. The default port is 8000. Stop with Ctrl+C; run the same command to restart.

## Data and security

Data stays in `data/noteshare.sqlite3` in this folder. Do not delete `data` when updating. Back up using SQLite's backup API, or stop the server before copying the entire data folder. Protect backups as private data. Notes are not encrypted at rest; use encrypted disks and restrict access to the host.

Passwords use Argon2id and require 12–128 characters at signup. Random 256-bit bearer tokens expire after 24 hours; only token hashes are stored. The browser keeps its token in memory, so refreshing requires logging in again. Log out revokes the current token. Every note operation checks ownership. Database queries are parameterized, note content is rendered as text, and responses include a restrictive content security policy and no-store caching. Login and signup attempts are rate limited in SQLite across server workers. Forwarded IP headers are deliberately not trusted; behind a proxy the IP limit applies to that proxy's users together.

Share links grant read access to the current saved contents of one note. Anyone who has a link can read it. Creating another link replaces the old one. Turning off sharing or deleting the note disables the link. Share tokens are stored hashed, and shared API responses disclose only the title and body. The server does not enable access logs, avoiding share-token logging by default; also redact `/s/*` and `/api/shared/*` paths in any proxy logs.

Before handling real data over the internet, serve through an HTTPS reverse proxy and block direct public access to the HTTP backend. Configure HSTS at that proxy, secure the host, and arrange tested backups. This implementation has automated security regression tests, but has not received an independent security audit. It does not include email verification or password recovery; email addresses are login identifiers, not verified identities. No third-party scripts or services receive notes.

## API

Send JSON using `Content-Type: application/json`. Except for signup, login, and shared reads, send `Authorization: Bearer <token>`.

| Method | Path | JSON / result |
|---|---|---|
| POST | `/api/signup` | `{ "email": "you@example.com", "password": "at-least-12-characters" }` → 201 |
| POST | `/api/login` | Same fields → `{ "token": "..." }` |
| POST | `/api/logout` | Revokes current session → 204 |
| GET | `/api/notes` | Array of your notes |
| POST | `/api/notes` | `{ "title": "Hello", "body": "My note" }` → note, 201 |
| GET | `/api/notes/<id>` | One owned note |
| PUT | `/api/notes/<id>` | Both title and body → updated note |
| DELETE | `/api/notes/<id>` | Deletes owned note → 204 |
| POST | `/api/notes/<id>/share` | Creates/replaces link → `{ "share_token": "..." }` |
| DELETE | `/api/notes/<id>/share` | Revokes link → 204 |
| GET | `/api/shared/<share_token>` | Public `{ "title": "...", "body": "..." }` |

Notes contain `id`, `title`, `body`, `updated_at` (Unix seconds), and `shared` (boolean). Titles must be nonblank and at most 200 characters; bodies are at most 50,000 characters. Request bodies are limited to 128 KiB. Errors are JSON `{ "error": "..." }`; common statuses are 400 invalid input, 401 authentication required, 404 missing or unowned note, 409 account unavailable, 413 oversized request, and 429 rate limit. Share pages are at `/s/<share_token>`. Cross-origin browser API access is disabled by default; native phone apps can use the bearer-token API directly.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary databases and cover ownership boundaries, private defaults, share rotation/revocation, deletion, password hashes, token expiry/logout, validation, security headers, rate limits, and persistence across reinitialization.
