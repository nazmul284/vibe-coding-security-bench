#!/bin/sh
set -eu
cd "$(dirname "$0")"
command -v python3 >/dev/null 2>&1 || { echo "Python 3 is required." >&2; exit 1; }
PORT="${PORT:-8000}" exec python3 app.py
