from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List
from collections.abc import Mapping, Sequence


def _run_git(args: Sequence[str], *, cwd: Path, timeout_seconds: float = 90.0) -> dict[str, Any]:
    cmd = ["git", *[str(a) for a in args]]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1.0, float(timeout_seconds)),
        )
        return {
            "ok": int(proc.returncode) == 0,
            "returncode": int(proc.returncode),
            "stdout": str(proc.stdout or ""),
            "stderr": str(proc.stderr or ""),
            "command": cmd,
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": -999,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "command": cmd,
        }


def collect_changed_paths(repo_root: Path, *, old_ref: str, new_ref: str) -> dict[str, Any]:
    if not old_ref or not new_ref or old_ref == new_ref:
        return {"ok": False, "paths": [], "error": "refs_missing_or_equal"}
    run = _run_git(["diff", "--name-only", f"{old_ref}..{new_ref}"], cwd=repo_root, timeout_seconds=180.0)
    if not run["ok"]:
        return {"ok": False, "paths": [], "error": str(run.get("stderr") or "").strip()}
    paths = [line.strip() for line in str(run.get("stdout") or "").splitlines() if line.strip()]
    return {"ok": True, "paths": paths, "error": ""}


def summarize_hotspots(paths: Sequence[str], *, top_n: int = 8) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for raw in paths:
        path = str(raw or "").strip().replace("\\", "/")
        if not path:
            continue
        parts = [p for p in path.split("/") if p]
        if not parts:
            continue
        key = parts[0] if len(parts) == 1 else f"{parts[0]}/{parts[1]}"
        counts[key] += 1
    return [{"path": p, "changed_files": int(n)} for p, n in counts.most_common(max(1, int(top_n)))]


def infer_focus_areas(hotspots: Sequence[Mapping[str, Any]]) -> list[str]:
    areas: list[str] = []
    keys = " ".join(str(item.get("path") or "").lower() for item in hotspots)
    if any(k in keys for k in ("plugins", "extension", "skill", "mcp")):
        areas.append("plugin_ecosystem_expansion")
    if any(k in keys for k in ("gateway", "api", "server", "acp")):
        areas.append("gateway_and_protocol_surface")
    if any(k in keys for k in ("security", "policy", "auth", "acl")):
        areas.append("security_policy_hardening")
    if any(k in keys for k in ("test", "tests", "e2e")):
        areas.append("test_depth_and_regression_control")
    if any(k in keys for k in ("ui", "web", "tui", "chat", "ios", "android")):
        areas.append("ui_and_operator_experience")
    if any(k in keys for k in ("memory", "model", "agent", "autonomy")):
        areas.append("agent_runtime_capability_growth")
    if not areas:
        areas.append("general_surface_growth")
    return areas


def recommend_counter_moves(focus_areas: Sequence[str]) -> list[str]:
    recs: list[str] = []
    if "plugin_ecosystem_expansion" in focus_areas:
        recs.append("Expand Thomas plugin runtime contract tests and keep plugin command coverage at or above competitor levels.")
    if "gateway_and_protocol_surface" in focus_areas:
        recs.append("Add gateway compatibility probes for new provider/protocol edges and keep p95 latency regressions gated.")
    if "security_policy_hardening" in focus_areas:
        recs.append("Increase policy and secret-scan strict checks and add negative authz tests for newly exposed routes.")
    if "test_depth_and_regression_control" in focus_areas:
        recs.append("Raise test LOC and e2e breadth for touched subsystems before release gate pass.")
    if "ui_and_operator_experience" in focus_areas:
        recs.append("Add operator workflow smoke tests for mission control and browser surfaces to protect UX velocity.")
    if "agent_runtime_capability_growth" in focus_areas:
        recs.append("Benchmark new model/runtime pathways weekly and enforce non-regression budgets on tool-call and token efficiency.")
    if "general_surface_growth" in focus_areas:
        recs.append("Monitor breadth growth and preemptively add targeted strict checks in the fastest-growing directories.")
    return recs


def build_prediction_evo_scope(
    *,
    agents: Sequence[Mapping[str, Any]],
    previous_registry_competitors: Mapping[str, Any],
    focus_agent: str,
) -> dict[str, Any]:
    focus = str(focus_agent or "").strip()
    by_competitor: dict[str, Any] = {}
    all_focus_areas: list[str] = []
    all_recs: list[str] = []
    for agent in agents:
        aid = str(agent.get("id") or "").strip()
        if not aid or aid == focus:
            continue
        version = dict(agent.get("version_info") or {})
        root = Path(str(agent.get("root") or "."))
        prev_entry = dict(previous_registry_competitors.get(aid) or {})
        prev_version = dict(prev_entry.get("version") or {})
        previous_head = str(prev_version.get("local_head") or "").strip()
        current_head = str(version.get("local_head") or "").strip()
        row: dict[str, Any] = {
            "competitor": aid,
            "root": str(root),
            "previous_head": previous_head,
            "current_head": current_head,
            "status": "no_previous_baseline",
            "changed_files_count": 0,
            "hotspots": [],
            "predicted_next_focus": [],
            "recommended_thomas_counter_moves": [],
        }
        if str(version.get("kind") or "") != "git":
            row["status"] = "non_git_source"
            by_competitor[aid] = row
            continue
        if previous_head and current_head and previous_head != current_head:
            diff = collect_changed_paths(root, old_ref=previous_head, new_ref=current_head)
            if diff.get("ok"):
                paths = list(diff.get("paths") or [])
                hotspots = summarize_hotspots(paths)
                focus_areas = infer_focus_areas(hotspots)
                recs = recommend_counter_moves(focus_areas)
                row.update(
                    {
                        "status": "updated_since_last_run",
                        "changed_files_count": len(paths),
                        "hotspots": hotspots,
                        "predicted_next_focus": focus_areas,
                        "recommended_thomas_counter_moves": recs,
                    }
                )
                all_focus_areas.extend(focus_areas)
                all_recs.extend(recs)
            else:
                row["status"] = "diff_failed"
                row["error"] = diff.get("error")
        elif previous_head and current_head and previous_head == current_head:
            row["status"] = "no_change_since_last_run"
        by_competitor[aid] = row

    focus_area_counts = Counter(all_focus_areas)
    rec_counts = Counter(all_recs)
    return {
        "focus_agent": focus,
        "competitors": by_competitor,
        "aggregate_predicted_focus": [
            {"area": area, "count": int(count)}
            for area, count in focus_area_counts.most_common()
        ],
        "aggregate_recommended_counter_moves": [
            {"move": move, "count": int(count)}
            for move, count in rec_counts.most_common()
        ],
    }

