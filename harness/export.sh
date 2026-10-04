#!/bin/bash
# Copy finished builds and results into the repo. No dependencies, databases or raw agent logs.
set -euo pipefail
B=${1:?builds dir}
R=$(cd "$(dirname "$0")/.." && pwd)
rm -rf "$R/builds" "$R/results/builds" "$R/results/reviews"
mkdir -p "$R/builds" "$R/results/builds" "$R/results/reviews"
for m in "$B"/*.meta.json; do
  n=$(basename "$m" .meta.json)
  rsync -a --exclude node_modules --exclude .venv --exclude venv --exclude __pycache__ \
        --exclude '*.db' --exclude '*.db-*' --exclude '*.sqlite*' --exclude data/ \
        --exclude '*.log' --exclude .git "$B/$n/" "$R/builds/$n/"
  cp "$m" "$R/results/builds/"
done
cp "$B"/reviews/*.json "$R/results/reviews/"
cp "$B/scores.jsonl" "$R/results/"
echo "exported $(ls "$R/builds" | wc -l) builds, $(ls "$R/results/reviews" | wc -l) reviews"
