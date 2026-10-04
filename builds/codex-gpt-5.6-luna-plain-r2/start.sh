#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v node >/dev/null 2>&1 || { echo "Node.js 18+ is required." >&2; exit 1; }
mkdir -p data
PORT="${PORT:-3000}" node server.js
