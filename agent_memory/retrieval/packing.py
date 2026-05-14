from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PackConfig:
    # Budget in characters (LLM token budgets vary; chars is stable)
    max_chars: int = 9000
    max_receipts: int = 10
    receipt_chars_each: int = 900
    include_recent_turns: int = 4

def _clip(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."

def pack_context(
    mode: str,
    pins: list[tuple[str, str]],
    l2_summary: str | None,
    receipts: list[dict[str, Any]],
    recent_turns: list[dict[str, Any]],
    cfg: PackConfig = PackConfig(),
) -> dict[str, Any]:
    # L1: mode + pins
    l1_lines = [f"MODE: {mode}"]
    for k, txt in pins:
        l1_lines.append(f"PIN[{k}]: {_clip(txt, 600)}")
    l1 = "\n".join(l1_lines).strip()

    # L2: summary
    l2 = (l2_summary or "").strip()

    # L3: receipts, verbatim
    l3_lines: list[str] = []
    for r in receipts[: cfg.max_receipts]:
        header = f"RECEIPT event_id={r['event_id']} thread={r.get('thread','')} ts={r.get('ts_utc','')}"
        body = _clip(r.get("text", ""), cfg.receipt_chars_each)
        l3_lines.append(header)
        l3_lines.append(body)
        l3_lines.append("")
    l3 = "\n".join(l3_lines).strip()

    # Recent turns (optional)
    rt_lines: list[str] = []
    for t in recent_turns[: cfg.include_recent_turns]:
        rt_lines.append(f"{t.get('etype','')}: {_clip(t.get('text',''), 500)}")
    recent_block = "\n".join(rt_lines).strip()

    # Priority truncation: never drop L3 entirely.
    parts = []
    if l1:
        parts.append(("L1", l1))
    if recent_block:
        parts.append(("RECENT", recent_block))
    if l2:
        parts.append(("L2", l2))
    if l3:
        parts.append(("L3", l3))

    out_lines: list[str] = []
    used = 0
    # Always reserve L3
    l3_len = len(l3) + 20 if l3 else 0
    budget = cfg.max_chars
    pre_budget = max(0, budget - l3_len)

    # Add L1 + RECENT + L2 as fits
    for tag, text in parts:
        if tag == "L3":
            continue
        block = f"## {tag}\n{text}\n"
        if used + len(block) <= pre_budget:
            out_lines.append(block)
            used += len(block)

    # Add L3 at the end (guaranteed)
    if l3:
        out_lines.append(f"## L3\n{l3}\n")

    packed = "\n".join(out_lines).strip()
    if len(packed) > budget:
        packed = packed[: budget - 3] + "..."
    return {"packed": packed, "l1": l1, "l2": l2, "l3": l3, "recent": recent_block}
