#!/bin/sh
set -eu
cd "$(dirname "$0")"
umask 077
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
exec .venv/bin/python app.py
