#!/bin/sh
set -eu

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt

PORT="${PORT:-8000}"
case "$PORT" in
  ''|*[!0-9]*) echo "PORT must be a number" >&2; exit 1 ;;
esac

exec .venv/bin/waitress-serve --host=0.0.0.0 --port="$PORT" --threads=6 app:app

