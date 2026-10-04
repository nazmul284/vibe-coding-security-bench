# NoteShare

Run it with:

```sh
PORT=8000 ./start.sh
```

Then open <http://127.0.0.1:8000>. The app uses only Python 3's standard library; `start.sh` creates the persistent `data/` directory and starts the server. SQLite data and hashed session tokens are kept there.

The API is served from the same address under `/api`. Passwords are hashed with scrypt, bearer tokens are stored only as SHA-256 hashes, notes are scoped to their owner, and shared links are unguessable, read-only capabilities. Set `HOST=0.0.0.0` to expose it on a network and `CORS_ORIGIN=https://your-phone-app.example` only when a separate client needs cross-origin API access.

For real internet-facing use, put it behind HTTPS and a reverse proxy with backups and firewall access controls. This small app intentionally does not include email verification, password reset, account deletion, or multi-user administration.
