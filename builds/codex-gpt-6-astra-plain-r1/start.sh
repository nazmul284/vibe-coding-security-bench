#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'NoteShare requires Python 3.9 or newer. Install Python from https://www.python.org/downloads/ and run this script again.' >&2
  exit 1
fi
# Uses the Python standard library; no packages need to be installed.
exec python3 app.py
