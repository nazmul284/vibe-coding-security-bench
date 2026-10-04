"""Join build metadata and scores into results/summary.json.

usage: python analyze.py <builds_dir> <results_dir>
"""
import json, sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

builds, results = Path(sys.argv[1]), Path(sys.argv[2])
scores = {}
for l in (builds / "scores.jsonl").read_text().splitlines():
    j = json.loads(l)
    scores[j["name"]] = j

KEYS = ["pw_slow_hash", "token_csprng", "no_hardcoded_secret", "token_expiry", "logout_revokes",
        "owner_checks", "share_token_strong", "login_rate_limit", "password_policy",
        "sql_parameterized", "xss_safe_render", "security_headers"]
adj_path = results / "adjudication.json"
adjudication = json.loads(adj_path.read_text()) if adj_path.exists() else {}
adjudication.pop("_note", None)

def review(name):
    """Both reviewers' grades; a disagreement uses the hand adjudication, keyed name/property."""
    g = {}
    for r in ("claude", "codex"):
        p = builds / "reviews" / f"{name}.{r}.json"
        if p.exists():
            g[r] = {k: bool(v["value"]) for k, v in json.loads(p.read_text()).items()}
    if not g:
        return None, 0
    out = {}
    for k in KEYS:
        vals = {g[r][k] for r in g}
        out[k] = vals.pop() if len(vals) == 1 else adjudication[f"{name}/{k}"]
    return out, len(g)

rows = []
for mf in sorted(builds.glob("*.meta.json")):
    m = json.loads(mf.read_text())
    s = scores.get(m["name"], {})
    sg = s.get("semgrep", [])
    deps = s.get("deps", {})
    func = s.get("functional", {})
    rv, n_reviewers = review(m["name"])
    rows.append({
        "review": rv, "reviewers": n_reviewers,
        "review_score": sum(rv.values()) if rv else None,
        **{k: m.get(k) for k in ("name", "agent", "model", "prompt", "rep", "wall_s", "cost_usd", "rc")},
        "loc": s.get("loc"),
        "stack": s.get("stack"),
        "sg_error": sum(f["severity"] == "ERROR" for f in sg),
        "sg_warning": sum(f["severity"] == "WARNING" for f in sg),
        "sg_info": sum(f["severity"] == "INFO" for f in sg),
        "sg_rules": sorted({f["rule"] for f in sg if f["severity"] != "INFO"}),
        "dep_tool": deps.get("tool"),
        "dep_total": deps.get("total"),
        "dep_high_crit": (deps.get("high") or 0) + (deps.get("critical") or 0),
        "dep_direct": sorted(k for k, v in deps.get("packages", {}).items() if v["direct"]),
        "security_packages": s.get("security_packages", []),
        "func_pass": sum(bool(v) for v in func.values()),
        "func_total": len(func),
        "works": bool(func) and all(func.values()),
    })

groups = defaultdict(list)
for r in rows:
    groups[(r["agent"], r["model"], r["prompt"])].append(r)

def agg(rs):
    sgf = [r["sg_error"] + r["sg_warning"] for r in rs]
    rv = [r["review_score"] for r in rs if r["review_score"] is not None]
    return {"n": len(rs),
            "review_scores": rv,
            "review_mean": round(mean(rv), 2) if rv else None,
            "works": sum(r["works"] for r in rs),
            "semgrep_findings_mean": round(mean(sgf), 2),
            "semgrep_findings": sgf,
            "dep_vulns": [r["dep_total"] for r in rs],
            "sec_pkgs_mean": round(mean(len(r["security_packages"]) for r in rs), 2),
            "loc_mean": round(mean(r["loc"] or 0 for r in rs)),
            "cost_usd_mean": round(mean(r["cost_usd"] for r in rs), 2) if all(r["cost_usd"] is not None for r in rs) else None,
            "wall_min_mean": round(mean(r["wall_s"] for r in rs) / 60, 1)}

prop_fail = {k: {p: sum(1 for r in rows if r["review"] and r["prompt"] == p and not r["review"][k])
                 for p in ("plain", "secure")} for k in KEYS}
summary = {"rows": rows, "property_failures": prop_fail,
           "cells": [{"agent": a, "model": m, "prompt": p, **agg(rs)} for (a, m, p), rs in sorted(groups.items())],
           "by_prompt": {p: agg([r for r in rows if r["prompt"] == p]) for p in ("plain", "secure")},
           "by_agent": {a: agg([r for r in rows if r["agent"] == a]) for a in ("claude", "codex")}}
results.mkdir(exist_ok=True)
(results / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps({k: summary[k] for k in ("by_prompt", "by_agent")}, indent=1))
