"""Fixed-width tables for the article and README, generated from results/summary.json.

usage: python tables.py <results_dir>
"""
import json, sys
from pathlib import Path

s = json.loads((Path(sys.argv[1]) / "summary.json").read_text())
LABEL = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5",
         "claude-haiku-4-5-20251001": "Haiku 4.5", "gpt-6-astra": "GPT-6-Astra",
         "gpt-5.6-sol": "GPT-5.6-Sol", "gpt-5.6-luna": "GPT-5.6-Luna"}
ORDER = list(LABEL)
cells = {(c["model"], c["prompt"]): c for c in s["cells"]}
fmt = lambda xs: ", ".join(str(x) for x in xs)

print("Security checks met, out of 12 (one number per build)\n")
print(f"{'agent':12}{'model':14}{'plain':>9}{'+ secure':>11}{'works':>8}{'Semgrep':>9}")
print(f"{'-'*11:12}{'-'*13:14}{'-'*8:>9}{'-'*9:>11}{'-'*6:>8}{'-'*7:>9}")
for m in ORDER:
    p, q = cells[(m, "plain")], cells[(m, "secure")]
    agent = "Claude Code" if m.startswith("claude") else "Codex"
    works = f"{p['works'] + q['works']}/{p['n'] + q['n']}"
    sg = sum(p["semgrep_findings"]) + sum(q["semgrep_findings"])
    print(f"{agent:12}{LABEL[m]:14}{fmt(p['review_scores']):>9}{fmt(q['review_scores']):>11}{works:>8}{sg:>9}")

print("\nBuilds missing each check (of 12 per prompt)\n")
NAMES = {"login_rate_limit": "login rate limit", "logout_revokes": "server-side logout",
         "security_headers": "security headers", "token_expiry": "token expiry",
         "password_policy": "8-char password min", "no_hardcoded_secret": "no hardcoded secret",
         "token_csprng": "random/secret token", "share_token_strong": "strong share token", "xss_safe_render": "safe HTML rendering"}
print(f"{'check':24}{'plain':>7}{'+ secure':>10}")
print(f"{'-'*23:24}{'-'*5:>7}{'-'*8:>10}")
for k, v in sorted(s["property_failures"].items(), key=lambda kv: -kv[1]["plain"]):
    if v["plain"] or v["secure"]:
        print(f"{NAMES.get(k, k):24}{v['plain']:>7}{v['secure']:>10}")
print(f"{'all other checks':24}{0:>7}{0:>10}")
