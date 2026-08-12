"""Render the workflow's rubric JSON to a human-readable RUBRIC.md (one-shot)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = sys.argv[1]
OUT = Path(__file__).resolve().parents[2] / "plans" / "thomas" / "chat_stress_2026-06-17" / "RUBRIC.md"

data = json.load(open(SRC, encoding="utf-8"))


def find(o):
    if isinstance(o, dict):
        if "dimensions" in o and "rubric_title" in o:
            return o
        for v in o.values():
            r = find(v)
            if r:
                return r
    if isinstance(o, list):
        for v in o:
            r = find(v)
            if r:
                return r
    return None


r = find(data) or data
L = []
bt = chr(96)  # backtick, avoids shell mangling in the generator itself
L.append("# " + r["rubric_title"])
L.append("")
L.append(
    "> Synthesized 2026-06-17 by a 6-perspective frontier-grounded panel workflow "
    "(thomas-chat-rubric), then merged and weighted by a lead-architect agent. "
    "Drives the headless harness in tests/stress/. Weights are normalized at scoring time."
)
L.append("")
L.append("## Philosophy")
L.append("")
L.append(r["philosophy"])
L.append("")
L.append("## Scoring method")
L.append("")
L.append(r["scoring_method"])
L.append("")
L.append("## Dimensions (by weight)")
L.append("")
dims = sorted(r["dimensions"], key=lambda x: -x.get("weight", 0))
for d in dims:
    L.append(f"### {d['name']}  (weight {d['weight']})")
    L.append("")
    L.append(f"- **id**: {bt}{d['id']}{bt}")
    L.append(f"- **grades observed failure**: {d.get('thomas_failure_mapped')}")
    L.append(f"- **Why it matters**: {d['why_it_matters']}")
    L.append(f"- **Frontier standard**: {d['frontier_standard']}")
    L.append(f"- **Automated probe**: {d['automated_probe']}")
    L.append("")
    L.append("| Score | Label | Criteria |")
    L.append("|---|---|---|")
    for lv in d["scoring_levels"]:
        crit = lv["criteria"].replace("|", "\\|").replace("\n", " ")
        L.append(f"| {lv['score']} | {lv['label']} | {crit} |")
    L.append("")

OUT.write_text("\n".join(L), encoding="utf-8")
print(f"RUBRIC.md written: {len(chr(10).join(L))} chars, {len(dims)} dimensions -> {OUT}")
