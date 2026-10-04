# NoteShare

Private notes with optional read-only share links.

## Run

    PORT=8000 ./start.sh

Then open http://localhost:8000. The first run creates `.venv/` and installs dependencies.
All data is stored in `data/noteshare.db` — back up that file to back up everything.

Optional environment variables:
- `HOST` — address to listen on (default `0.0.0.0`).
- `TRUST_PROXY=1` — set only when running behind a reverse proxy (e.g. Caddy/nginx) that provides HTTPS, so client IPs and https are detected correctly.

## API

All bodies are JSON. Authenticated requests send `Authorization: Bearer <token>`.

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | /api/signup | `{email, password}` | password ≥ 8 chars |
| POST | /api/login | `{email, password}` | returns `{token, expires_at}`; tokens last 30 days |
| POST | /api/logout | | invalidates the token |
| GET | /api/me | | `{id, email}` |
| GET | /api/notes | | list of your notes |
| POST | /api/notes | `{title, body}` | returns the note with `id` |
| GET | /api/notes/<id> | | |
| PUT | /api/notes/<id> | `{title, body}` | |
| DELETE | /api/notes/<id> | | |
| POST | /api/notes/<id>/share | | returns `{share_token, url}` (same token if already shared) |
| DELETE | /api/notes/<id>/share | | stop sharing; old link stops working |
| GET | /api/shared/<share_token> | | no login needed |

Errors are returned as `{"error": "..."}` with a matching HTTP status. Notes belonging to
other users always return 404.
