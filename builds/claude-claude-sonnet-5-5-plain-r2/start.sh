#!/bin/sh
# Installs what NoteShare needs and starts the server on $PORT (default 8000).
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --quiet -r requirements.txt
export PORT="${PORT:-8000}"
exec .venv/bin/python app.py
