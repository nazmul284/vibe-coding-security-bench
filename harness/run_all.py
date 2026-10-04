"""Build every cell of the matrix, a few at a time, then score each build.

usage: python run_all.py <builds_dir> [--reps 2] [--jobs 3] [--score-only]
"""
import argparse, json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELS = [("claude", "claude-opus-5-5"), ("claude", "claude-sonnet-5-5"),
          ("claude", "claude-haiku-4-5-20251001"),
          ("codex", "gpt-6-astra"), ("codex", "gpt-5.6-sol"), ("codex", "gpt-5.6-luna")]
PROMPTS = ["plain", "secure"]

ap = argparse.ArgumentParser()
ap.add_argument("builds")
ap.add_argument("--reps", type=int, default=2)
ap.add_argument("--jobs", type=int, default=3)
ap.add_argument("--score-only", action="store_true")
a = ap.parse_args()
builds = Path(a.builds).resolve()
builds.mkdir(parents=True, exist_ok=True)

# rep-major order, alternating agents, so a partial run is still balanced
cells = [(ag, m, p, r) for r in range(1, a.reps + 1) for p in PROMPTS for ag, m in MODELS]

def build(cell):
    ag, m, p, r = cell
    name = f"{ag}-{m}-{p}-r{r}"
    if (builds / f"{name}.meta.json").exists():
        return name
    out = subprocess.run([sys.executable, HERE / "build.py", ag, m, p, str(r), builds],
                         capture_output=True, text=True)
    print(out.stdout.strip() or out.stderr[-300:], flush=True)
    return name

if not a.score_only:
    print(f"{len(cells)} builds, {a.jobs} at a time", flush=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        list(ex.map(build, cells))

results = builds / "scores.jsonl"
done = {json.loads(l)["name"] for l in results.read_text().splitlines()} if results.exists() else set()
for i, (ag, m, p, r) in enumerate(cells):
    name = f"{ag}-{m}-{p}-r{r}"
    if name in done or not (builds / name).exists():
        continue
    out = subprocess.run([sys.executable, HERE / "score.py", builds / name, str(8710 + i)],
                         capture_output=True, text=True, timeout=900)
    line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else json.dumps(
        {"name": name, "score_error": out.stderr[-300:]})
    with results.open("a") as f:
        f.write(line + "\n")
    print("scored", name, flush=True)
