# NoteShare

A small private notebook with a responsive web interface, JSON API, and revocable read-only sharing.

## Start

You need Python 3.10 or newer installed. Open a terminal in this folder and run:

```sh
./start.sh
```

Open **http://localhost:3000**. To choose a port:

```sh
PORT=8080 ./start.sh
```

The script installs pinned dependencies into `.venv` and runs the Waitress server (not Flask's development server). Set `HOST=127.0.0.1` to allow only local connections. Press Ctrl+C to stop. Run the same command to restart.

Create an account with an email and a password of 12–128 characters. Create, edit, delete, search and share notes in the browser. Save before sharing. Each new share link replaces the previous link; “Stop sharing” revokes it. Deleting a note also revokes sharing. Sharing exposes the current saved content to anyone with that link.

Browser login tokens are kept in memory, not local storage. Reloading requires logging in again. Sessions expire after 24 hours; logging out immediately revokes the current session. Email addresses are account identifiers, not verified addresses. This version does not offer password recovery or email verification.

## Data and deployment

All account, note, session and rate-limit data stays in `data/noteshare.sqlite3` in this folder. Do not delete `data` or put it in a public web directory. No external database or service is needed. SQLite files have owner-only permissions. Notes are stored as plaintext inside the database: administrators with filesystem access can read them. Passwords use salted scrypt hashes; session and sharing tokens use 256 bits of randomness and only their SHA-256 hashes are stored.

Before allowing real people to use it over the internet, put it behind an **HTTPS reverse proxy** or a hosting platform that provides HTTPS, restrict direct access to the backend port, and set `TRUSTED_HOSTS` to your hostname (comma-separated if multiple). The application does not provision a public domain or TLS certificate. Do not transmit real credentials through public HTTP. Keep server access restricted and use encrypted disk storage and backups. The app does not trust forwarded client IP headers: behind a proxy, rate limits are shared by clients on that proxy. Configure additional per-client limits at the proxy for a larger deployment. Disable or redact API shared-token URL logging in your proxy; these URLs are secrets. Page share links use URL fragments and a no-referrer policy.

To back up reliably, stop the server and copy the entire `data` folder to a secure location, then restart. Restore the entire folder while the server is stopped. For online backups use SQLite's backup API, not a copy of just the live main database file.

Security measures include parameterized SQL, owner-scoped access for every private note operation, bounded request and field sizes, persistent authentication throttling, generic login errors, no cookie authentication or cross-origin API access, no-store responses, restrictive CSP and frame protection, and text-only note rendering. Signup duplicate errors can reveal that an email is registered. There is no claim of an independent security audit. A larger public service should add email verification/recovery, storage quotas, monitoring and deployment-specific security review. The list endpoint returns all of the user's notes; pagination would be appropriate for larger collections.

## JSON API

Use `Content-Type: application/json` for JSON request bodies. Authenticated requests use `Authorization: Bearer <token>`. Errors return `{"error":"..."}` and an appropriate HTTP status. Times are Unix timestamps in seconds.

| Method | Path | Body / result |
| --- | --- | --- |
| POST | `/api/signup` | `{ "email": "you@example.com", "password": "a long unique passphrase" }` → 201 |
| POST | `/api/login` | Same fields → `{ "token": "..." }` |
| POST | `/api/logout` | Revokes current token → 204 |
| GET | `/api/notes` | Array of your notes |
| POST | `/api/notes` | `{ "title": "Title", "body": "Text" }` → created note, 201 |
| GET | `/api/notes/<id>` | One owned note |
| PUT | `/api/notes/<id>` | Both `title` and `body` → updated note |
| DELETE | `/api/notes/<id>` | Deletes note → 204 |
| POST | `/api/notes/<id>/share` | Creates/replaces link → `{ "share_token": "..." }` |
| DELETE | `/api/notes/<id>/share` | Revokes link → 204 |
| GET | `/api/shared/<share_token>` | Public read-only note, no login |

Private note objects contain `id`, `title`, `body`, `created_at`, `updated_at`, and `is_shared`. Public note objects omit `is_shared` and never contain account details. Titles are 1–200 characters; bodies can be empty and are limited to 50,000 characters. A missing note and a note owned by somebody else both return 404. No untrusted ownership or sharing fields from clients are accepted.

The web share URL is `https://your-host/share#<share_token>`. The browser removes the fragment after loading the note; reopening that shortened URL will not reload it. Use the original copied link to visit it again.

## Tests

After running the start script at least once:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary databases and check ownership, CRUD, public sharing, rotation/revocation, deletion, persistence, expiry, logout, hashing, validation, injection payloads, security headers and throttling.

Security header choices follow the [Flask security documentation](https://flask.palletsprojects.com/en/stable/web-security/).
