"""Compare the two reviewers property by property. Lists every disagreement.

usage: python agreement.py <reviews_dir>
"""
import json, sys
from pathlib import Path

d = Path(sys.argv[1])
agree = total = 0
for c in sorted(d.glob("*.claude.json")):
    name = c.name[:-len(".claude.json")]
    x = d / f"{name}.codex.json"
    if not x.exists():
        continue
    a, b = json.loads(c.read_text()), json.loads(x.read_text())
    for k in a:
        total += 1
        if bool(a[k]["value"]) == bool(b[k]["value"]):
            agree += 1
        else:
            print(f"{name:44} {k:20} claude={a[k]['value']!s:5} codex={b[k]['value']}")
            print(f"    claude: {a[k]['evidence'][:150]} {a[k].get('note','')[:120]}")
            print(f"    codex:  {b[k]['evidence'][:150]} {b[k].get('note','')[:120]}")
print(f"agreement {agree}/{total}")
