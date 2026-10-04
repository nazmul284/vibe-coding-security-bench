"""Run both reviewers over every finished build, a few at a time. Skips work already done.

usage: python review_all.py <builds_dir> [--jobs 4]
"""
import subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
builds = Path(sys.argv[1]).resolve()
jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 4
out = builds / "reviews"
names = [m.name[:-len(".meta.json")] for m in sorted(builds.glob("*.meta.json"))]
work = [(r, n) for n in names for r in ("claude", "codex") if not (out / f"{n}.{r}.json").exists()]

def run(job):
    r, n = job
    p = subprocess.run([sys.executable, HERE / "review.py", r, builds / n, out],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    print((p.stdout.strip() or f"FAILED {n} {r}: {p.stderr[-200:]}"), flush=True)

print(len(work), "reviews", flush=True)
with ThreadPoolExecutor(jobs) as ex:
    list(ex.map(run, work))
