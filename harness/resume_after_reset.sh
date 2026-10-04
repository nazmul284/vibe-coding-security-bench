#!/bin/bash
# Codex hit its ChatGPT usage limit at ~12:18 on 2026-10-04 (reset 15:22). Finish the Codex work.
set -u
B=/private/tmp/claude-501/-Users-nazmul-pp-medium-article/98fa3038-1a73-42db-8ae5-0b5c5839da81/scratchpad/builds
H=/Users/nazmul/pp/medium_article/articles/vibe-coding-security-claude-code-codex/repo/harness
until [ "$(date +%H%M)" -ge 1527 ]; do sleep 60; done
echo "resume $(date)"
for n in codex-gpt-5.6-sol-secure-r2 codex-gpt-6-astra-secure-r2; do
  rm -rf "$B/$n" "$B/$n.meta.json" "$B/$n.log" "$B/reviews/$n".*
  grep -v "\"name\": \"$n\"" "$B/scores.jsonl" > "$B/scores.tmp" && mv "$B/scores.tmp" "$B/scores.jsonl"
done
python3 -u $H/run_all.py $B --reps 2 --jobs 2
python3 -u $H/review_all.py $B --jobs 3
for img in hero lock; do
  before=$(ls -t ~/.codex/generated_images/*/*.png 2>/dev/null | head -1)
  (cd /Users/nazmul/pp/medium_article/articles/vibe-coding-security-claude-code-codex/images && codex exec --skip-git-repo-check --ephemeral -s workspace-write "$(cat $H/${img}_prompt.txt)" < /dev/null > $B/img-$img.log 2>&1)
  after=$(ls -t ~/.codex/generated_images/*/*.png 2>/dev/null | head -1)
  [ "$after" != "$before" ] && cp "$after" "/Users/nazmul/pp/medium_article/articles/vibe-coding-security-claude-code-codex/images/gen-$img.png" && echo "image $img -> gen-$img.png"
done
echo "resume done $(date)"
