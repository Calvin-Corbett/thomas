from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from collections.abc import Mapping


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updated_at_utc": "", "runs": [], "competitors": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "updated_at_utc": "", "runs": [], "competitors": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "updated_at_utc": "", "runs": [], "competitors": {}}
    payload.setdefault("version", 1)
    payload.setdefault("updated_at_utc", "")
    payload.setdefault("runs", [])
    payload.setdefault("competitors", {})
    return payload


def render_registry_markdown(registry: Mapping[str, Any]) -> str:
    competitors = dict(registry.get("competitors") or {})
    runs = list(registry.get("runs") or [])
    lines: list[str] = []
    lines.append("# Competitor Registry")
    lines.append("")
    lines.append(f"- Updated at: `{registry.get('updated_at_utc')}`")
    lines.append(f"- Recorded runs: `{len(runs)}`")
    lines.append("")
    lines.append("## Last Known Competitor State")
    lines.append("")
    lines.append("| Competitor | Last Tested (UTC) | Version | Up To Date | Model (Day Snapshot) | Last Score | Last Result |")
    lines.append("|---|---|---|---|---|---:|---|")
    for cid in sorted(competitors.keys()):
        row = dict(competitors.get(cid) or {})
        version = dict(row.get("version") or {})
        model = dict(row.get("model_snapshot") or {})
        result_json = str(row.get("last_result_json") or "").strip()
        version_text = str(version.get("local_head") or version.get("version") or "n/a")
        up_to_date = version.get("is_up_to_date")
        up_text = "yes" if up_to_date is True else ("no" if up_to_date is False else "unknown")
        model_text = str(model.get("model") or model.get("profile") or "n/a")
        lines.append(
            f"| `{cid}` | `{row.get('last_tested_at_utc')}` | `{version_text}` | `{up_text}` | `{model_text}` | "
            f"`{row.get('last_composite_score')}` | `{result_json}` |"
        )
    lines.append("")
    lines.append("## Recent Runs")
    lines.append("")
    if not runs:
        lines.append("- none")
        lines.append("")
        return "\n".join(lines)
    for run in runs[-20:][::-1]:
        lines.append(
            f"- `{run.get('computed_at_utc')}` suite=`{run.get('suite_id')}` "
            f"result=`{run.get('result_json_path')}`"
        )
    lines.append("")
    return "\n".join(lines)

