# NoteShare

A small private notes app with share links and a JSON API. It uses only Python's standard library and SQLite, so there are no packages to install.

## Start

```sh
PORT=8000 ./start.sh
```

Open `http://localhost:8000`. Persistent data is stored in `data/noteshare.db`.

## API

Sign up with `POST /api/signup`, log in with `POST /api/login`, and send the returned token as `Authorization: Bearer <token>` for note endpoints. The public `GET /api/shared/<share_token>` endpoint does not require authentication.
