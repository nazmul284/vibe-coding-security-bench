#!/usr/bin/env bash
# Installs NoteShare's dependencies (first run only) and starts the server on $PORT.
set -euo pipefail
cd "$(dirname "$0")"
umask 077  # data files readable only by this user

if [ ! -x .venv/bin/python ]; then
  echo "Setting up Python environment..."
  python3 -m venv .venv
fi
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
  touch .venv/.installed
fi

export PORT="${PORT:-8000}"
exec .venv/bin/python app.py
