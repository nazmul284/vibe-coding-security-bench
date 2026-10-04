# NoteShare

A small private notes app with a browser interface and JSON API.

## Start

```sh
PORT=8000 ./start.sh
```

Data is stored in `noteshare.db` in this folder. Put the app behind an HTTPS reverse proxy in production; bearer tokens and shared notes must not travel over plain HTTP.

Passwords must be at least 12 characters. Login tokens expire after 30 days. Creating a new share link for a note invalidates its previous share link.
