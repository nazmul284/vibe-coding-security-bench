#!/bin/sh
set -eu
cd "$(dirname "$0")"
umask 077
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
exec .venv/bin/gunicorn --bind "0.0.0.0:${PORT:-8000}" --workers 2 --threads 4 --timeout 30 app:app
