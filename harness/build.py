"""Run one vibe-coding build: hand the prompt to an agent, accept everything, read nothing.

usage: python build.py <agent> <model> <prompt: plain|secure> <rep> <builds_dir>
"""
import json, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
agent, model, prompt_name, rep, builds = sys.argv[1:6]
prompt = (HERE.parent / "prompts" / f"{prompt_name}.txt").read_text()
name = f"{agent}-{model}-{prompt_name}-r{rep}"
out = Path(builds) / name
if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True)

if agent == "claude":
    cmd = ["claude", "-p", prompt, "--model", model,
           "--dangerously-skip-permissions",
           "--setting-sources", "project",          # no user hooks, plugins or memory
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--no-session-persistence", "--output-format", "json"]
elif agent == "codex":
    cmd = ["codex", "exec", "-m", model,
           "--dangerously-bypass-approvals-and-sandbox",
           "--ignore-user-config", "--ignore-rules",  # no user config or rules
           "--ephemeral", "--skip-git-repo-check", "--json", "-C", str(out), prompt]
else:
    sys.exit(f"unknown agent {agent}")

t0 = time.time()
log = out.parent / f"{name}.log"
try:
    # a distinct PORT per build, so parallel builds testing their own servers don't collide
    import os, zlib
    env = {**os.environ, "PORT": str(9000 + zlib.crc32(name.encode()) % 900)}
    p = subprocess.run(cmd, cwd=out, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45 * 60)
    rc, stdout, stderr = p.returncode, p.stdout, p.stderr
except subprocess.TimeoutExpired as e:
    rc, stdout, stderr = "timeout", e.stdout or "", e.stderr or ""
    stdout = stdout.decode() if isinstance(stdout, bytes) else stdout
    stderr = stderr.decode() if isinstance(stderr, bytes) else stderr
wall = round(time.time() - t0, 1)
log.write_text(stdout + "\n--- stderr ---\n" + stderr)

meta = {"name": name, "agent": agent, "model": model, "prompt": prompt_name,
        "rep": int(rep), "rc": rc, "wall_s": wall}
if agent == "claude":
    try:
        j = json.loads(stdout)
        meta.update(cost_usd=j.get("total_cost_usd"), turns=j.get("num_turns"),
                    is_error=j.get("is_error"))
    except Exception:
        pass
else:
    # last turn.completed event carries token usage
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") == "turn.completed":
            meta["usage"] = ev.get("usage")
(out.parent / f"{name}.meta.json").write_text(json.dumps(meta, indent=2))
print(json.dumps(meta))
