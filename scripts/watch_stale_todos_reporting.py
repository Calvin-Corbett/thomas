from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def report_payload(repo_root: Path, markers: list[Any], stale_days: int) -> dict[str, Any]:
    stale = [row for row in markers if row.stale]
    fresh = [row for row in markers if not row.stale]
    top_stale = stale[:50]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "repo_root": str(repo_root),
        "stale_days_threshold": stale_days,
        "totals": {
            "markers": len(markers),
            "stale_markers": len(stale),
            "fresh_markers": len(fresh),
            "files_with_markers": len({row.path for row in markers}),
            "files_with_stale_markers": len({row.path for row in stale}),
        },
        "top_stale_markers": [
            {
                "path": row.path,
                "line": row.line,
                "kind": row.kind,
                "text": row.text,
                "author": row.author,
                "commit": row.commit,
                "committed_at": row.committed_at.isoformat() if row.committed_at else None,
                "age_days": row.age_days,
            }
            for row in top_stale
        ],
    }


def markdown_report(payload: dict[str, Any]) -> str:
    generated_at = payload.get("generated_at", "")
    threshold = payload.get("stale_days_threshold", 0)
    totals = payload.get("totals", {})
    rows = payload.get("top_stale_markers", [])
    lines = [
        "# Stale TODO Audit",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Stale threshold: `{threshold}` days",
        f"- Total markers: `{totals.get('markers', 0)}`",
        f"- Stale markers: `{totals.get('stale_markers', 0)}`",
        f"- Fresh markers: `{totals.get('fresh_markers', 0)}`",
        f"- Files with markers: `{totals.get('files_with_markers', 0)}`",
        f"- Files with stale markers: `{totals.get('files_with_stale_markers', 0)}`",
        "",
        "## Top Stale Markers",
        "",
    ]
    if not rows:
        lines.append("No stale TODO-style markers found.")
        return "\n".join(lines) + "\n"
    for row in rows:
        lines.append(
            f"- `{row['path']}:{row['line']}` [{row['kind']}] age=`{row.get('age_days')}` author=`{row.get('author')}`"
        )
        lines.append(f"  `{row.get('text', '')}`")
    return "\n".join(lines) + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


def fingerprint(payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "stale_days_threshold": payload.get("stale_days_threshold"),
            "totals": payload.get("totals"),
            "top_stale_markers": payload.get("top_stale_markers"),
        },
        ensure_ascii=True,
        sort_keys=True,
    )
