#!/usr/bin/env bash
# Installs what NoteShare needs (into a private .venv in this folder) and starts it.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt

export PORT="${PORT:-8000}"
umask 077   # data files are readable only by the user running the server
exec .venv/bin/python app.py
