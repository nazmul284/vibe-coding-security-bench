#!/usr/bin/env bash
# Starts NoteShare. Uses only Python 3 (no extra packages needed).
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required but was not found." >&2
  if command -v brew >/dev/null 2>&1; then
    echo "Installing Python 3 with Homebrew..." >&2
    brew install python
  elif command -v apt-get >/dev/null 2>&1; then
    echo "Installing Python 3 with apt-get..." >&2
    sudo apt-get update && sudo apt-get install -y python3
  else
    echo "Please install Python 3 from https://www.python.org/downloads/ and run this again." >&2
    exit 1
  fi
fi

export PORT="${PORT:-8000}"
mkdir -p data
exec python3 server.py
