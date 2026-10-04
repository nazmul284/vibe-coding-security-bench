#!/bin/sh
# Installs dependencies into a local virtualenv and starts NoteShare.
# Usage: PORT=8000 ./start.sh      (set HOST=0.0.0.0 to accept outside connections)
set -e
cd "$(dirname "$0")"
: "${PORT:?Please set the PORT environment variable, e.g. PORT=8000 ./start.sh}"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  .venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt
  touch .venv/.installed
fi
exec .venv/bin/python app.py
