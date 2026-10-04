"""Grade one build against rubric.md with a read-only reviewer.

usage: python review.py <claude|codex> <build_dir> <out_dir>
Each build is graded by both reviewers; disagreements are resolved by hand from the
cited evidence (results/adjudication.json).
"""
import json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
reviewer, build, outdir = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3])
rubric = (HERE / "rubric.md").read_text()
KEYS = ["pw_slow_hash", "token_csprng", "no_hardcoded_secret", "token_expiry", "logout_revokes",
        "owner_checks", "share_token_strong", "login_rate_limit", "password_policy",
        "sql_parameterized", "xss_safe_render", "security_headers"]

if reviewer == "claude":
    cmd = ["claude", "-p", rubric, "--model", "claude-opus-5-5",
           "--allowedTools", "Read", "Grep", "Glob",
           "--disallowedTools", "Bash", "Write", "Edit", "WebFetch", "WebSearch",
           "--setting-sources", "project", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--no-session-persistence", "--output-format", "json"]
    p = subprocess.run(cmd, cwd=build, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1200)
    text = json.loads(p.stdout)["result"]
else:
    last = outdir / f"{build.name}.codex.last.txt"
    cmd = ["codex", "exec", "-m", "gpt-6-astra", "-s", "read-only", "--ignore-user-config",
           "--ignore-rules", "--ephemeral", "--skip-git-repo-check", "-C", str(build),
           "-o", str(last), rubric]
    p = subprocess.run(cmd, cwd=build, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1200)
    text = last.read_text()

m = re.search(r"\{.*\}", text, re.S)
grade = json.loads(m.group(0))
missing = [k for k in KEYS if k not in grade]
if missing:
    raise SystemExit(f"{build.name} {reviewer}: missing {missing}")
outdir.mkdir(parents=True, exist_ok=True)
(outdir / f"{build.name}.{reviewer}.json").write_text(json.dumps(grade, indent=2))
print(build.name, reviewer, sum(bool(grade[k]["value"]) for k in KEYS), "/ 12")
