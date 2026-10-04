# NoteShare

Private notes with optional share links. Web page + JSON API.

## Run it

    PORT=8000 ./start.sh

Then open http://localhost:8000. Needs only Python 3 (no extra packages).
All data lives in `data/noteshare.db` — back up that folder to keep your notes.

## API

All bodies are JSON. Except signup, login and shared, send `Authorization: Bearer <token>`.

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /api/signup | {"email","password"} | 201 {"id","email"} (password ≥ 8 chars) |
| POST | /api/login | {"email","password"} | {"token"} (valid 30 days) |
| POST | /api/logout | – | {"ok": true} |
| GET | /api/notes | – | list of notes |
| POST | /api/notes | {"title","body"} | 201 note |
| GET | /api/notes/<id> | – | note |
| PUT | /api/notes/<id> | {"title","body"} | updated note |
| DELETE | /api/notes/<id> | – | {"ok": true} |
| POST | /api/notes/<id>/share | – | {"share_token"} |
| DELETE | /api/notes/<id>/share | – | {"ok": true} (turns the link off) |
| GET | /api/shared/<share_token> | – | {"title","body","updated_at"} (no login) |

A note looks like `{"id","title","body","share_token","created_at","updated_at"}`.
Errors look like `{"error": "message"}`. Another user's note gives 404.
Readable share page for friends: `/s/<share_token>`.
