# NoteShare

Run: `PORT=8000 ./start.sh` then open http://localhost:8000

Data lives in `data/noteshare.db` (back up this file). Needs python3.
Extra API calls beyond the basics: `POST /api/logout`, `DELETE /api/notes/<id>/share` (stop sharing).
Put it behind HTTPS (e.g. Caddy or nginx) before real use.
