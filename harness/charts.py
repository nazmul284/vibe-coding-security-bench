"""Results figure: security checks met per build, plain vs "make it secure".

usage: uv run --with matplotlib python charts.py <results_dir> <out.png>
"""
import json, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

s = json.loads((Path(sys.argv[1]) / "summary.json").read_text())
LABEL = {"claude-opus-5-5": "Claude Code · Opus 5.5", "claude-sonnet-5-5": "Claude Code · Sonnet 5.5",
         "claude-haiku-4-5-20251001": "Claude Code · Haiku 4.5", "gpt-6-astra": "Codex · GPT-6-Astra",
         "gpt-5.6-sol": "Codex · GPT-5.6-Sol", "gpt-5.6-luna": "Codex · GPT-5.6-Luna"}
order = list(LABEL)[::-1]
cells = {(c["model"], c["prompt"]): c for c in s["cells"]}
PLAIN, SECURE, INK, MUTED, BG = "#9a9a9a", "#c2410c", "#1f2328", "#6b7280", "#ffffff"

fig, ax = plt.subplots(figsize=(10, 5.6), dpi=200)
fig.patch.set_facecolor(BG)
for i, m in enumerate(order):
    for prompt, color, dy in (("plain", PLAIN, 0.13), ("secure", SECURE, -0.13)):
        xs = cells[(m, prompt)]["review_scores"]
        # two builds per cell; nudge exact duplicates apart so both dots stay visible
        for j, x in enumerate(sorted(xs)):
            off = 0.12 * (j - (len(xs) - 1) / 2) if len(set(xs)) == 1 else 0
            ax.scatter(x + off, i + dy, s=70, color=color, zorder=3, edgecolor="white", linewidth=0.8)
    ax.axhline(i, color="#eeeeee", lw=8, zorder=0)
ax.set_yticks(range(len(order)), [LABEL[m] for m in order], fontsize=10.5, color=INK)
ax.set_xlim(3.5, 12.8)
ax.set_xticks(range(4, 13))
ax.set_xlabel("security checks met, out of 12", fontsize=10, color=MUTED)
for sp in ("top", "right", "left"):
    ax.spines[sp].set_visible(False)
ax.tick_params(axis="y", length=0)
ax.tick_params(axis="x", colors=MUTED)
ax.scatter([], [], s=70, color=PLAIN, label="plain prompt")
ax.scatter([], [], s=70, color=SECURE, label='+ "Make sure it\'s secure."')
ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.13), ncol=2, frameon=False, fontsize=10)
fig.text(0.02, 0.965, "The model mattered more than the security sentence", fontsize=15,
         weight="bold", color=INK, ha="left")
fig.text(0.02, 0.915, "24 vibe-coded builds of one notes app, two per cell. Every build passed the functional test.",
         fontsize=10.5, color=MUTED, ha="left")
fig.text(0.02, 0.015, "Claude Code 2.1.289 · Codex CLI 0.154.0 · 12-point code review by two reviewers · "
         "Apple M2, 2026-10-04 · github.com/nazmul284/vibe-coding-security-bench",
         fontsize=7.5, color=MUTED, ha="left")
fig.subplots_adjust(left=0.25, right=0.97, top=0.86, bottom=0.2)
fig.savefig(sys.argv[2], facecolor=BG)
print("wrote", sys.argv[2])
