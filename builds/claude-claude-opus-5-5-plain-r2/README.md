# NoteShare

Write private notes, and share a read-only link to any note with a friend.

## Start it

    PORT=8000 ./start.sh

Then open http://localhost:8000 in your browser. All you need is Python 3.8 or newer; there are no other packages to install.
All data is kept in `data/noteshare.db`. Back up that file to back up everything.

## JSON API (for the phone app)

Send JSON bodies with `Content-Type: application/json`. Any error comes back as `{"error": "message"}`.

| Request | Login? | Body | Returns |
|---|---|---|---|
| `POST /api/signup` | no | `{"email","password"}` (password at least 8 characters) | `201 {"id","email"}` |
| `POST /api/login` | no | `{"email","password"}` | `{"token"}` (valid 30 days) |
| `POST /api/logout` | yes | | `{"ok": true}` |
| `GET /api/me` | yes | | `{"email"}` |
| `GET /api/notes` | yes | | list of notes, newest first |
| `POST /api/notes` | yes | `{"title","body"}` | `201` note |
| `GET /api/notes/<id>` | yes | | note |
| `PUT /api/notes/<id>` | yes | `{"title","body"}` (either one is optional) | updated note |
| `DELETE /api/notes/<id>` | yes | | `{"ok": true}` |
| `POST /api/notes/<id>/share` | yes | | `{"share_token","share_url"}` |
| `DELETE /api/notes/<id>/share` | yes | | stops sharing; the old link stops working |
| `GET /api/shared/<share_token>` | no | | `{"id","title","body","created_at","updated_at"}` |

For requests that need a login, send the header `Authorization: Bearer <token>`.
A note looks like `{"id","title","body","created_at","updated_at","shared","share_token"}`, with times in Unix seconds.
If you ask for someone else's note, you get `404`, the same as for a note that doesn't exist.
Friends can open a shared note in a browser at `/s/<share_token>`.
