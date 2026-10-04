#!/usr/bin/env bash
# Installs NoteShare's dependencies (first run only) and starts the server.
# Usage: PORT=8000 ./start.sh
set -euo pipefail
cd "$(dirname "$0")"

# Files created by the app (the database) are readable only by this user.
umask 077

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from https://www.python.org/downloads/" >&2
  exit 1
fi

export PORT="${PORT:-8000}"

if [ ! -x .venv/bin/python ]; then
  echo "Setting up NoteShare (first run)..."
  python3 -m venv .venv
fi

# Reinstall only when requirements.txt changes.
if ! cmp -s requirements.txt .venv/.installed-requirements 2>/dev/null; then
  .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
  cp requirements.txt .venv/.installed-requirements
fi

exec .venv/bin/python app.py
