#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${PORT:=8000}"
mkdir -p data
chmod 700 data
exec python3 server.py
