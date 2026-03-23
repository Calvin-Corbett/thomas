#!/usr/bin/env python3
"""Classify an agent task into a lightweight startup lane."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
ROUTER_DOC = "docs/ai/AGENT_ROUTER.md"
LANE_CARD_PATHS = {
    "chat": "docs/ai/CHECKLISTS/agent-lane-chat.md",
    "simple-edit": "docs/ai/CHECKLISTS/agent-lane-simple-edit.md",
    "risky-edit": "docs/ai/CHECKLISTS/agent-lane-risky-edit.md",
    "multi-file": "docs/ai/CHECKLISTS/agent-lane-multi-file.md",
    "multi-agent": "docs/ai/CHECKLISTS/agent-lane-multi-agent.md",
    "ui-proof": "docs/ai/CHECKLISTS/agent-lane-ui-proof.md",
}
UI_PROOF_PREFIXES = (
    "apps/site/src/app/",
    "apps/site/src/components/",
)
RISKY_PREFIXES = (
    "thomas/server/routes/",
    "thomas/server/web/",
    "scripts/workboard_",
    "plans/thomas/",
)
WORKBOARD_REQUIRED_LANES = {"risky-edit", "multi-file", "multi-agent", "ui-proof"}
DATE_RE = re.compile(r"Last updated:\s*(?P<value>\d{4}-\d{2}-\d{2})")


def _load_agent_preflight_module():
    module_path = Path(__file__).with_name("agent_preflight.py")
    spec = importlib.util.spec_from_file_location("agent_preflight", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load agent_preflight from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_preflight = _load_agent_preflight_module()


def _relpath(path_value: str) -> str:
    raw = str(path_value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(ROOT)
            return str(candidate).replace("\\", "/")
        except (OSError, ValueError):
            return str(candidate).replace("\\", "/")
    return raw.lstrip("./")


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = str(value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _load_workflow_mode() -> str:
    try:
        from thomas.preferences.store import PreferencesStore, get_db_path

        prefs = PreferencesStore(db_path=get_db_path()).get(user_id="default")
        mode = str(getattr(getattr(prefs.advanced, "interface", None), "workflow_mode", "") or "").strip().lower()
        if mode in {"guided", "expert"}:
            return mode
    except (ImportError, AttributeError, OSError, sqlite3.Error, TypeError, ValueError):
        pass
    return "guided"


def _find_guardrails(paths: list[str]) -> list[str]:
    found: list[str] = []
    for raw in paths:
        rel = _relpath(raw)
        if not rel:
            continue
        candidate = (ROOT / rel).resolve()
        cursor = candidate if candidate.is_dir() else candidate.parent
        for parent in (cursor, *cursor.parents):
            if parent == ROOT.parent:
                break
            guard = parent / "GUARDRAILS.md"
            if guard.exists():
                try:
                    rel_guard = guard.resolve().relative_to(ROOT)
                    found.append(str(rel_guard).replace("\\", "/"))
                except (OSError, ValueError):
                    found.append(str(guard).replace("\\", "/"))
            if parent == ROOT:
                break
    return _unique(found)


def _parse_workboard_claims(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "active_claims": 0,
            "matching_claims": [],
            "conflict": False,
            "stale": False,
            "updated_at": "",
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    updated_at = ""
    stale = False
    for line in text.splitlines()[:20]:
        match = DATE_RE.search(line)
        if not match:
            continue
        updated_at = match.group("value")
        try:
            then = datetime.fromisoformat(updated_at).replace(tzinfo=timezone.utc)
            stale = (datetime.now(timezone.utc) - then).days >= 7
        except ValueError:
            stale = False
        break
    in_claims = False
    claims: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_claims = stripped.lower().startswith("## agent claims")
            continue
        if not in_claims or not stripped.startswith("- "):
            continue
        token = stripped[2:].strip()
        if token.lower() in {"none", "- none"}:
            continue
        fields: dict[str, str] = {}
        for part in [piece.strip() for piece in token.split(";") if piece.strip()]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            fields[key.strip().lower()] = value.strip()
        if fields:
            claims.append(fields)
    return {
        "exists": True,
        "active_claims": len(claims),
        "claims": claims,
        "stale": stale,
        "updated_at": updated_at,
    }


def _paths_overlap(path_a: str, path_b: str) -> bool:
    a = _relpath(path_a)
    b = _relpath(path_b)
    if not a or not b:
        return False
    return a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")


def _matching_claims(paths: list[str], workboard: dict[str, Any]) -> list[dict[str, str]]:
    rows = list(workboard.get("claims") or [])
    if not paths:
        return []
    matches: list[dict[str, str]] = []
    for claim in rows:
        scope_value = str(claim.get("scope") or "")
        scopes = [item.strip() for item in scope_value.split(",") if item.strip()]
        if any(_paths_overlap(task_path, scope_path) for task_path in paths for scope_path in scopes):
            matches.append(claim)
    return matches


def _requires_ui_proof(paths: list[str]) -> bool:
    return any(_relpath(path).startswith(prefix) for path in paths for prefix in UI_PROOF_PREFIXES)


def _is_risky_path(path: str) -> bool:
    rel = _relpath(path)
    if not rel:
        return False
    if rel in {
        "AGENTS.md",
        "README.md",
        "PROJECT_INDEX.md",
        "KNOWN_ISSUES.md",
        "docs/REPO_STRUCTURE_PROTOCOL.md",
        "docs/AGENT_FILE_EDITING_RULES.md",
        "GUARDRAILS.md",
    }:
        return True
    return any(rel.startswith(prefix) for prefix in RISKY_PREFIXES)


def _subsystems(paths: list[str]) -> set[str]:
    out: set[str] = set()
    for rel in [_relpath(path) for path in paths]:
        if not rel:
            continue
        parts = [part for part in rel.split("/") if part]
        if len(parts) >= 2:
            out.add("/".join(parts[:2]))
        elif parts:
            out.add(parts[0])
    return out


def classify_task(
    *,
    summary: str,
    paths: list[str],
    edit_intent: bool,
    tracked_work: bool,
    multi_agent: bool,
    long_running: bool,
    workflow_mode: str,
    workboard_path: Path,
) -> dict[str, Any]:
    workboard = _parse_workboard_claims(workboard_path)
    matching_claims = _matching_claims(paths, workboard)
    conflict = bool(matching_claims)
    ui_proof = _requires_ui_proof(paths)
    risky_paths = [path for path in paths if _is_risky_path(path)]
    subsystem_count = len(_subsystems(paths))
    summary_lower = str(summary or "").lower()
    delegation_keywords = any(
        token in summary_lower for token in ("delegate", "swarm", "parallel", "multi-agent", "handoff", "workers")
    )

    if not edit_intent and not paths:
        lane = "chat"
    elif ui_proof:
        lane = "ui-proof"
    elif multi_agent or delegation_keywords:
        lane = "multi-agent"
    elif long_running or len(paths) >= 4 or subsystem_count >= 3:
        lane = "multi-file"
    elif tracked_work or conflict or risky_paths:
        lane = "risky-edit"
    else:
        lane = "simple-edit"

    workboard_required = lane in WORKBOARD_REQUIRED_LANES or tracked_work or long_running or conflict or multi_agent
    reads: list[str] = [ROUTER_DOC, LANE_CARD_PATHS[lane]]
    if lane != "chat":
        reads.extend(["docs/AGENT_FILE_EDITING_RULES.md", "GUARDRAILS.md"])
        reads.extend(_find_guardrails(paths))
    if lane in {"risky-edit", "multi-file", "multi-agent"} and workflow_mode == "guided":
        reads.append("AGENTS.md")
    if lane == "multi-file" and workflow_mode == "guided":
        reads.append("docs/REPO_STRUCTURE_PROTOCOL.md")
    if lane == "multi-agent":
        reads.extend(["plans/thomas/WORKBOARD.md", "docs/ops/TASK_ECOSYSTEM_PROTOCOL.md"])
    if lane == "ui-proof":
        reads.append("skills/ui-precision-guard/SKILL.md")

    checks = {
        "chat": [],
        "simple-edit": [
            "Run a file-level syntax or compile check for edited code.",
            "Run focused regression tests for changed behavior.",
        ],
        "risky-edit": [
            "Run focused regression tests for changed behavior.",
            "Run python scripts/test_stepup_protocol.py when the change needs repo-wide regression confidence.",
            "Run release hygiene checks when product behavior changes.",
            "Validate workboard claim requirements if tracked work is required.",
        ],
        "multi-file": [
            "Run focused regression tests across changed subsystems.",
            "Run python scripts/test_stepup_protocol.py and carry it through the large shard stage before handoff.",
            "Run release hygiene checks.",
            "Update plan/workboard state when execution intent changes.",
        ],
        "multi-agent": [
            "Claim scope before implementation.",
            "Use workboard messaging for blockers and coordination.",
            "Mark READY and log ACK before bundling another agent's scope.",
        ],
        "ui-proof": [
            "Run python scripts/refresh_site_visual_proof.py",
            "Run python scripts/check_site_visual_proof.py",
        ],
    }[lane]
    escalation = {
        "chat": [
            "You start editing files.",
            "The task becomes multi-file, risky, or multi-agent.",
        ],
        "simple-edit": [
            "Scope expands beyond a small isolated change.",
            "A claim conflict appears.",
            "Visual proof, release hygiene, or architecture review becomes required.",
        ],
        "risky-edit": [
            "The task spans multiple subsystems.",
            "Delegation or handoff becomes necessary.",
        ],
        "multi-file": [
            "Parallel lanes or delegation are required.",
            "A UI-proof or release-critical flow is added.",
        ],
        "multi-agent": [
            "UI-proof or release-critical gates also apply.",
        ],
        "ui-proof": [
            "The task also becomes multi-agent or architecture-heavy.",
        ],
    }[lane]
    return {
        "lane": lane,
        "workflow_mode": workflow_mode,
        "edit_intent": bool(edit_intent),
        "workboard_required": bool(workboard_required),
        "workboard": {
            "path": str(workboard_path),
            "active_claims": int(workboard.get("active_claims", 0) or 0),
            "matching_claims": matching_claims,
            "claim_conflict": bool(conflict),
            "stale": bool(workboard.get("stale", False)),
            "updated_at": str(workboard.get("updated_at") or ""),
        },
        "flags": {
            "ui_proof": bool(ui_proof),
            "tracked_work": bool(tracked_work),
            "multi_agent": bool(multi_agent),
            "long_running": bool(long_running),
            "risky_paths": _unique([_relpath(path) for path in risky_paths]),
        },
        "paths": _unique([_relpath(path) for path in paths]),
        "required_reads": _unique(reads),
        "required_checks": checks,
        "escalation_triggers": escalation,
    }


def build_startup_payload(
    *,
    summary: str,
    paths: list[str],
    edit_intent: bool,
    tracked_work: bool,
    multi_agent: bool,
    long_running: bool,
    workflow_mode: str,
    workboard_path: Path,
    cwd: Path | None = None,
) -> dict[str, Any]:
    payload = classify_task(
        summary=summary,
        paths=paths,
        edit_intent=edit_intent,
        tracked_work=tracked_work,
        multi_agent=multi_agent,
        long_running=long_running,
        workflow_mode=workflow_mode,
        workboard_path=workboard_path,
    )
    payload["preflight"] = agent_preflight.evaluate_preflight(root=ROOT, cwd=cwd)
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify a Thomas agent task into a startup lane.")
    parser.add_argument("--summary", default="", help="Short task summary.")
    parser.add_argument("--path", action="append", default=[], help="Repo-relative path the task will touch.")
    parser.add_argument("--edit-intent", action="store_true", help="Set when the task will edit files.")
    parser.add_argument(
        "--tracked-work", action="store_true", help="Set when the task should be tracked on the workboard."
    )
    parser.add_argument(
        "--multi-agent", action="store_true", help="Set when the task needs delegation or swarm behavior."
    )
    parser.add_argument(
        "--long-running", action="store_true", help="Set when the task is expected to stay active across handoffs."
    )
    parser.add_argument(
        "--workflow-mode",
        choices=("guided", "expert"),
        default="",
        help="Override the saved workflow mode preference.",
    )
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD), help="Path to WORKBOARD.md.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    return parser


def _text_output(payload: dict[str, Any]) -> str:
    preflight = dict(payload.get("preflight") or {})
    policy = dict(preflight.get("policy") or {})
    lines = ["Thomas agent startup router"]
    if preflight:
        lines.extend(
            [
                f"preflight_status: {preflight['status']}",
                f"preflight_summary: {preflight['summary']}",
                f"preflight_policy: {policy.get('summary', '')}",
            ]
        )
        checks = list(preflight.get("checks") or [])
        if checks:
            lines.append("preflight_checks:")
            for check in checks:
                action = str(check.get("user_action") or "").strip()
                suffix = f" | action: {action}" if action and check.get("status") != "ok" else ""
                lines.append(
                    f"  - {check.get('status', 'unknown')} {check.get('id', 'check')}: {check.get('message', '')}{suffix}"
                )
    lines.extend(
        [
            f"lane: {payload['lane']}",
            f"workflow_mode: {payload['workflow_mode']}",
            f"workboard_required: {payload['workboard_required']}",
            (
                'workboard: '
                f"{payload['workboard']['active_claims']} active claims"
                + ("; conflict detected" if payload["workboard"]["claim_conflict"] else "")
                + ("; metadata stale" if payload["workboard"]["stale"] else "")
            ),
        ]
    )
    if payload["paths"]:
        lines.append("paths:")
        lines.extend([f"  - {path}" for path in payload["paths"]])
    lines.append("required_reads:")
    lines.extend([f"  - {item}" for item in payload["required_reads"]])
    lines.append("required_checks:")
    if payload["required_checks"]:
        lines.extend([f"  - {item}" for item in payload["required_checks"]])
    else:
        lines.append("  - none")
    lines.append("escalate_when:")
    lines.extend([f"  - {item}" for item in payload["escalation_triggers"]])
    return "\n".join(lines)


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    workflow_mode = str(args.workflow_mode or "").strip().lower() or _load_workflow_mode()
    payload = build_startup_payload(
        summary=str(args.summary or ""),
        paths=list(args.path or []),
        edit_intent=bool(args.edit_intent),
        tracked_work=bool(args.tracked_work),
        multi_agent=bool(args.multi_agent),
        long_running=bool(args.long_running),
        workflow_mode=workflow_mode,
        workboard_path=Path(str(args.workboard)).expanduser(),
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_text_output(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
