# NoteShare

A small private notes app with share links and a JSON API. It uses Python's standard library and SQLite, so it has no third-party dependencies.

## Start

```sh
PORT=8000 ./start.sh
```

Then open `http://localhost:8000`. Persistent data is stored in `data/noteshare.db`.

## API

Send and receive JSON. After login, include `Authorization: Bearer <token>` on all note endpoints.

- `POST /api/signup` — `{ "email": "...", "password": "..." }`
- `POST /api/login` — returns `{ "token": "..." }`
- `GET /api/notes`
- `POST /api/notes` — `{ "title": "...", "body": "..." }`
- `GET /api/notes/<id>`
- `PUT /api/notes/<id>` — `{ "title": "...", "body": "..." }`
- `DELETE /api/notes/<id>`
- `POST /api/notes/<id>/share` — returns `{ "share_token": "..." }`
- `GET /api/shared/<share_token>` — public; no login required

Passwords are salted and hashed with PBKDF2. Login tokens and share-token lookup values are hashed in the database.
