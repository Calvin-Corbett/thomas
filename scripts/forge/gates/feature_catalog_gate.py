"""Enforce canonical feature catalog coverage and structure.

This gate prevents drift between major platform capabilities and
their documented feature index.
"""

from __future__ import annotations

import re
from pathlib import Path

import sys
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "docs" / "FEATURE_CATALOG.md"

REQUIRED_HEADERS: list[str] = [
    "# Thomas Feature Catalog",
    "## Interfaces",
    "## Agent And Execution",
    "## Autonomy Platform",
    "## Model Platform",
    "## Memory And Knowledge",
    "## Benchmarking And Demos",
    "## Server, Security, And Operations",
]

REQUIRED_FEATURE_IDS: set[str] = {
    "ui.web_chat",
    "ui.repl_cli",
    "ui.live_browser_smoke",
    "integration.telegram",
    "realtime.voice_ws",
    "agent.intent_routing",
    "agent.multi_mode_execution",
    "tools.registry_and_execution",
    "guardrails.policy_and_approvals",
    "autonomy.jobs_engine",
    "autonomy.objective_state_machine",
    "autonomy.workflow_task",
    "autonomy.media_jobs",
    "autonomy.objective_api",
    "model.discovery_handshake",
    "model.protocol_validation",
    "model.capability_registry",
    "model.batch_chat_mode",
    "memory.thread_and_global",
    "memory.fabric_v2",
    "library.research_store",
    "demo.head_to_head_harness",
    "demo.dual_browser_runner",
    "demo.multi_run_campaign",
    "server.remote_access_control",
    "security.secret_storage",
    "observability.run_store_and_journal",
    "upgrade.doppelganger",
}

FEATURE_LINE_RE = re.compile(r"^- \[([a-z0-9_.-]+)\] .+", flags=re.MULTILINE)


def run() -> int:
    if not CATALOG.exists():
        print(f"Feature catalog gate failed: missing file {CATALOG}")
        return 1

    text = CATALOG.read_text(encoding="utf-8")

    missing_headers = [header for header in REQUIRED_HEADERS if header not in text]
    found_ids = FEATURE_LINE_RE.findall(text)
    found_set = set(found_ids)
    duplicate_ids = sorted({fid for fid in found_ids if found_ids.count(fid) > 1})
    missing_ids = sorted(REQUIRED_FEATURE_IDS - found_set)

    failed = False
    if missing_headers:
        failed = True
        print("Feature catalog gate failed: missing required headers:")
        for header in missing_headers:
            print(f"  - {header}")

    if missing_ids:
        failed = True
        print("Feature catalog gate failed: missing required feature IDs:")
        for fid in missing_ids:
            print(f"  - {fid}")

    if duplicate_ids:
        failed = True
        print("Feature catalog gate failed: duplicate feature IDs:")
        for fid in duplicate_ids:
            print(f"  - {fid}")

    if len(found_set) < len(REQUIRED_FEATURE_IDS):
        failed = True
        print(
            "Feature catalog gate failed: feature count below required floor "
            f"({len(found_set)} < {len(REQUIRED_FEATURE_IDS)})."
        )

    if failed:
        return 1

    print("Feature catalog gate: OK")
    print(f"  file: {CATALOG}")
    print(f"  documented feature IDs: {len(found_set)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
