# NoteShare

A small private notes app with a browser interface and JSON API.

## Start

```sh
PORT=8000 ./start.sh
```

Open `http://localhost:8000`. Data is stored in `noteshare.db` in this folder.

For an internet-facing deployment, put NoteShare behind an HTTPS reverse proxy. The application intentionally does not trust forwarded client-IP headers by default.

## API

Send JSON with `Content-Type: application/json`. After login, pass the returned token as `Authorization: Bearer <token>`.

- `POST /api/signup` — `{"email":"...","password":"..."}`
- `POST /api/login` — `{"email":"...","password":"..."}`
- `GET /api/notes`
- `POST /api/notes` — `{"title":"...","body":"..."}`
- `GET /api/notes/<id>`
- `PUT /api/notes/<id>` — `{"title":"...","body":"..."}`
- `DELETE /api/notes/<id>`
- `POST /api/notes/<id>/share`
- `GET /api/shared/<share_token>` — no authentication required

Passwords require at least 10 characters. Login tokens expire after 30 days. Creating a new share link for a note invalidates its previous share link.

