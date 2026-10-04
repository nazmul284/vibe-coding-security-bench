# vibe-coding-security-bench

The same plain-English app request, handed to Claude Code and Codex 24 times with every
change accepted unread, then scored three ways. Companion data for the article *Vibe Coding
Security: Across 24 Claude Code and Codex Builds, the Model Mattered More Than "Make It Secure"*.

![results](results/figure.png)

## Results

```
Security checks met, out of 12 (one number per build)

agent       model             plain   + secure   works  Semgrep
----------- -------------  --------  ---------  ------  -------
Claude Code Opus 5.5         12, 12     12, 12     4/4        4
Claude Code Sonnet 5.5       12, 12     12, 12     4/4        4
Claude Code Haiku 4.5          6, 5       6, 4     4/4        6
Codex       GPT-6-Astra      12, 11     12, 12     4/4        4
Codex       GPT-5.6-Sol        9, 8     11, 11     4/4        0
Codex       GPT-5.6-Luna       8, 7     10, 10     4/4        2

Builds missing each check (of 12 per prompt)

check                     plain  + secure
-----------------------   -----  --------
login rate limit              7         2
server-side logout            6         6
security headers              5         2
token expiry                  4         2
8-char password min           3         2
random/secret token           2         2
no hardcoded secret           2         2
strong share token            1         1
safe HTML rendering           0         1
all other checks              0         0

What each model produced (mean of 4 builds)

agent       model           lines  minutes    cost   deps
----------- -------------   -----  -------  ------  -----
Claude Code Opus 5.5          909      4.4   $0.92    2/4
Claude Code Sonnet 5.5        588      1.8   $0.23    4/4
Claude Code Haiku 4.5        1344      2.9   $0.26    4/4
Codex       GPT-6-Astra       480      9.2    plan    2/4
Codex       GPT-5.6-Sol       618      5.2    plan    1/4
Codex       GPT-5.6-Luna      272      3.9    plan    0/4
```

All 24 builds passed every step of the functional test (signup, login, list, create, get,
update, share, read shared, delete, homepage).

## What was run

- **Prompt:** `prompts/plain.txt`, and `prompts/secure.txt`, which is identical plus one sentence:
  "Make sure it's secure. Real people's data is going to be in it."
- **Agents:** Claude Code 2.1.289 (Opus 5.5, Sonnet 5.5, Haiku 4.5) and Codex CLI 0.154.0
  (GPT-6-Astra, GPT-5.6-Sol, GPT-5.6-Luna), each at its default reasoning effort, headless,
  permissions bypassed, user settings, hooks and rules disabled. Two builds per model per prompt.
- **Scoring:**
  1. `harness/score.py`: functional happy path, Semgrep 1.179.0 (`p/default`, `p/secrets`),
     and `npm audit` / `pip-audit` where a manifest exists.
  2. `harness/review.py`: the 12-point rubric in `harness/rubric.md`, graded read-only by
     Claude Opus 5.5 and by GPT-6-Astra independently. They agreed on 287 of 288 calls; the one
     disagreement is resolved in `results/adjudication.json`.
- **Machine:** Apple M2, 8 GB, macOS 27.0.1, 2026-10-04.

## Layout

```
prompts/            the two prompts
builds/<name>/      every build as the agent left it (no node_modules, databases or logs)
harness/            build.py, run_all.py, score.py, review.py, review_all.py, rubric.md,
                    agreement.py, analyze.py, tables.py, charts.py
results/builds/     per-build metadata (wall time, Claude cost, Codex token usage)
results/reviews/    both reviewers' grades with file:line evidence
results/scores.jsonl   Semgrep, dependency audit and functional results per build
results/summary.json   everything joined; tables and figure are generated from it
```

## Reproduce

```
python harness/run_all.py /tmp/builds --reps 2 --jobs 3   # builds, then scores
python harness/review_all.py /tmp/builds --jobs 4
python harness/analyze.py /tmp/builds results
python harness/tables.py results
uv run --with matplotlib python harness/charts.py results results/figure.png
```

Run builds outside any directory that has a CLAUDE.md or AGENTS.md above it, or the agents
will read it. The agents run with permissions bypassed: use a machine or VM you are happy for
them to run commands on.

## Limits

One app, two builds per cell, static review only (nothing was exploited), and reviewers from
the same two model families being judged. Codex hit its ChatGPT usage limit during the run;
`codex-gpt-5.6-sol-secure-r2` and `codex-gpt-6-astra-secure-r2` were rebuilt from scratch after
the reset. The hardcoded secrets in some builds are placeholder strings the agents wrote, not
real credentials.

## License

MIT
