#!/bin/sh
# Starts NoteShare. Needs Python 3.8+ (no extra packages to install).
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it from https://www.python.org/downloads/" >&2
  exit 1
fi

mkdir -p data
export PORT="${PORT:-8000}"
exec python3 server.py
