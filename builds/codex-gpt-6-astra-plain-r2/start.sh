#!/bin/sh
set -eu
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'NoteShare requires Python 3.9 or newer. Please install Python from python.org.' >&2
  exit 1
fi
# All dependencies are included with Python; no package downloads are needed.
exec python3 server.py
