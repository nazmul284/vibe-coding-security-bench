# NoteShare

Private notes with optional share links. Includes a web page and a JSON API.

## Run it

    PORT=8000 ./start.sh

Then open http://localhost:8000. The first run installs what it needs into `.venv/`
(this needs Python 3 and internet access). Your data is stored in `data/noteshare.db`.

**Back up `data/`.** It holds every account and note.

## Putting it on the internet

Use HTTPS. Without it, passwords and notes travel over the network unencrypted.
Put a reverse proxy such as Caddy or nginx in front of NoteShare to handle HTTPS, then start with:

    HOST=127.0.0.1 TRUST_PROXY=1 PORT=8000 ./start.sh

`HOST=127.0.0.1` makes NoteShare reachable only through the proxy. `TRUST_PROXY=1` lets
rate limiting see real visitor IP addresses. Only set it when a proxy on the same machine is in front.
With Caddy, the whole proxy config can be:

    notes.example.com {
        reverse_proxy 127.0.0.1:8000
    }

## API

Send `Authorization: Bearer <token>` with every request except signup, login and shared notes.

| Method | Path | Body | Result |
|---|---|---|---|
| POST | /api/signup | `{"email","password"}` | 201 `{"id","email"}` |
| POST | /api/login | `{"email","password"}` | `{"token"}` (valid 30 days) |
| POST | /api/logout | | ends that token |
| GET | /api/me | | `{"id","email"}` |
| GET | /api/notes | | list of notes |
| POST | /api/notes | `{"title","body"}` | 201, note with `id` |
| GET | /api/notes/<id> | | note |
| PUT | /api/notes/<id> | `{"title","body"}` | updated note |
| DELETE | /api/notes/<id> | | `{"ok": true}` |
| POST | /api/notes/<id>/share | | `{"share_token"}` |
| DELETE | /api/notes/<id>/share | | turns the share link off |
| GET | /api/shared/<share_token> | | `{"title","body","updated_at"}`, no login needed |

A note looks like `{"id","title","body","share_token","created_at","updated_at"}`. Times are Unix seconds.
Errors look like `{"error": "message"}`. The web share link for a note is `/s/<share_token>`.

## Tests

With the server running: `.venv/bin/python test_api.py http://127.0.0.1:8000`
(it creates two throwaway test accounts).
