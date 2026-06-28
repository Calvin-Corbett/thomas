"""Render the adversarial-discovery workflow result into a markdown findings doc."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = sys.argv[1]
OUT = Path(__file__).resolve().parents[2] / "plans" / "thomas" / "chat_stress_2026-06-17" / "FINDINGS_ADVERSARIAL.md"

data = json.load(open(SRC, encoding="utf-8"))


def find(o):
    if isinstance(o, dict):
        if "confirmed" in o and "total_proposed" in o:
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
findings = r["confirmed"]
# normalize a stray verifier severity
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "med": 2, "low": 3, "keep": 1}
for f in findings:
    s = (f.get("severity") or "medium").lower()
    if s == "keep":
        s = "high"  # the #12 tool-gating finding is security-relevant
    f["_sev"] = s
findings.sort(key=lambda f: SEV_ORDER.get(f["_sev"], 2))

L = []
L.append("# Adversarial discovery — confirmed NEW failure modes")
L.append("")
L.append(
    f"> Found by the `thomas-chat-failure-discovery` workflow (2026-06-17): "
    f"{r['total_proposed']} proposed across 6 pipeline slices, **{r['confirmed_new']} confirmed** "
    f"after each was handed to a skeptic agent told to refute it against the real code. "
    f"These are DISTINCT from the 7 defects in REPORT.md."
)
L.append("")
from collections import Counter

c = Counter(f["_sev"] for f in findings)
L.append(
    f"**Severity:** {c.get('critical', 0)} critical · {c.get('high', 0)} high · "
    f"{c.get('medium', 0) + c.get('med', 0)} medium · {c.get('low', 0)} low"
)
L.append("")
for i, f in enumerate(findings, 1):
    L.append(f"## {i}. {f.get('title', '')}")
    L.append("")
    L.append(
        f"- **Severity:** {f['_sev']} · **Slice:** {f.get('slice', '')} · **Dimension:** {f.get('rubric_dimension', '')}"
    )
    L.append(f"- **Mechanism:** {f.get('mechanism', '')}")
    L.append(f"- **Evidence:** {f.get('evidence', '')}")
    L.append(f"- **Headless probe:** {f.get('headless_probe', '')}")
    vr = f.get("verifier_reason", "")
    if vr:
        L.append(f"- **Verifier (skeptic) confirmation:** {vr}")
    L.append("")

OUT.write_text("\n".join(L), encoding="utf-8")
print(f"FINDINGS_ADVERSARIAL.md written: {len(chr(10).join(L))} chars, {len(findings)} findings -> {OUT}")
