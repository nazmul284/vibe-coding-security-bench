# NoteShare

Run it with:

```sh
PORT=8000 ./start.sh
```

Open http://127.0.0.1:8000. Data is stored in `noteshare.sqlite3` in this folder. The server uses only Python's standard library, so `start.sh` does not need internet access or package installation.

The API uses bearer tokens as documented in the request. The browser UI uses the same token in a Secure-by-default `HttpOnly`, `SameSite=Strict` cookie. For production or internet exposure, put it behind HTTPS and a reverse proxy with additional network controls and backups.
