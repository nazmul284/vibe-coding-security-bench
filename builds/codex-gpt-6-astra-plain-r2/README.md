# NoteShare

A small, responsive notes app with email/password accounts, private notes, and read-only share links. Uses Python's standard library and SQLite. No external packages or services are required.

## Start

With Python 3.9 or newer installed, run this in the project folder:

```sh
./start.sh
```

Open **http://localhost:3000**. To use another port:

```sh
PORT=8080 ./start.sh
```

Create an account from the login page, then click **New note**. Save your note or click **Share link** to save it and generate a read-only link. **Stop sharing** immediately disables that link. Editing a shared note updates what its link shows. Deleting a note disables its link too. Unsaved edits have a discard confirmation.

Data is stored in `data/noteshare.sqlite3` in this folder and survives server restarts. Keep the entire `data` folder. To back it up simply, stop the server and copy that folder. Do not commit it to version control. Browser sessions use sessionStorage (cleared when the tab session ends); server tokens expire after 30 days and can be revoked by logging out.

## JSON API

Send `Content-Type: application/json` for JSON bodies. Except for signup, login, and reading shared notes, send `Authorization: Bearer <token>`. Errors return `{"error":"message"}` and an appropriate HTTP status. Timestamps are Unix seconds.

| Method | Path | JSON body / response |
| --- | --- | --- |
| POST | `/api/signup` | `{ "email": "you@example.com", "password": "at least 8 characters" }` → 201 with `{id,email}` |
| POST | `/api/login` | `{email,password}` → `{token}` |
| GET | `/api/notes` | Array of your notes, most recently updated first |
| POST | `/api/notes` | `{title,body}` → 201 with the saved note |
| GET | `/api/notes/<id>` | Your note |
| PUT | `/api/notes/<id>` | `{title,body}` → updated note |
| DELETE | `/api/notes/<id>` | 204, empty body |
| POST | `/api/notes/<id>/share` | `{share_token}`; repeated calls return the current link token |
| GET | `/api/shared/<share_token>` | Shared note, no login needed |
| DELETE | `/api/notes/<id>/share` | Revoke sharing; returns `{ "share_token": null }` |
| POST | `/api/logout` | Revoke current login token; 204 |

Notes have `id`, `title`, `body`, `created_at`, `updated_at`, and `share_token` (null when private). Public responses omit `share_token`. Titles are required and limited to 200 characters; bodies may be empty and are limited to 200,000 characters. Passwords must have 8–1024 characters. Another user's note returns 404 for every private operation.

Web share URLs use `/shared/<share_token>`. Share links are bearer secrets: anyone who receives the URL can read that note. Login and share tokens are independently generated with secure randomness. Passwords use salted scrypt hashes, and login tokens are stored as hashes. Note text is displayed as plain text, never interpreted as HTML.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests run an isolated HTTP server and temporary database. They cover two-account isolation, CRUD, validation, authentication, logout, public sharing, revocation, deletion, and persistence after restarting the server.

## Hosting

The server listens on `0.0.0.0` at `$PORT` (default 3000). For public internet hosting, place it behind an HTTPS reverse proxy with request rate limiting, especially on signup and login. This small app uses Python's built-in HTTP server; it does not include email verification, password reset, or distributed hosting. A native phone app can use the JSON API directly. Browser clients on a different origin need a deliberate CORS policy, which is not enabled by default.
