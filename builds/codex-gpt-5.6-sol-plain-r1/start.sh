#!/bin/sh
set -eu

cd "$(dirname "$0")"
mkdir -p data
exec python3 server.py
