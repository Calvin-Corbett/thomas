from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_router_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "crew" / "brief" / "startup_router.py"
    spec = importlib.util.spec_from_file_location("crew_brief_startup_router", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_router_module()


def _write_workboard(tmp_path: Path, claims_block: str = "- none") -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "Last updated: 2026-03-18\n\n"
            "## Agent Claims\n\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n\n"
            "- none\n"
        ),
        encoding="utf-8",
    )
    return path


def test_router_classifies_chat_lane(tmp_path: Path) -> None:
    payload = mod.classify_task(
        summary="Answer a repo question",
        paths=[],
        edit_intent=False,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
    )

    assert payload["lane"] == "chat"
    assert payload["required_checks"] == []
    assert payload["workboard_required"] is False


def test_router_classifies_simple_edit_lane(tmp_path: Path) -> None:
    payload = mod.classify_task(
        summary="Patch a small bug",
        paths=["thomas/core/config.py"],
        edit_intent=True,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
    )

    assert payload["lane"] == "simple-edit"
    assert payload["workboard_required"] is True
    assert "plans/thomas/WORKBOARD.md" in payload["required_reads"]
    assert payload["required_checks"][0] == "Bootstrap a workboard claim before implementation."
    assert "docs/AGENT_FILE_EDITING_RULES.md" in payload["required_reads"]


def test_router_classifies_ui_proof_lane(tmp_path: Path) -> None:
    payload = mod.classify_task(
        summary="Update the website hero",
        paths=["apps/site/src/app/page.tsx"],
        edit_intent=True,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
    )

    assert payload["lane"] == "ui-proof"
    assert payload["workboard_required"] is True
    assert "skills/ui-precision-guard/SKILL.md" in payload["required_reads"]


def test_router_escalates_claim_conflict_to_risky_lane(tmp_path: Path) -> None:
    workboard = _write_workboard(
        tmp_path,
        "- agent=Codex 7; scope=thomas/core/config.py; task=runtime lane",
    )
    payload = mod.classify_task(
        summary="Patch config flow",
        paths=["thomas/core/config.py"],
        edit_intent=True,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=workboard,
    )

    assert payload["lane"] == "risky-edit"
    assert payload["workboard_required"] is True
    assert payload["workboard"]["claim_conflict"] is True
    assert payload["workboard"]["matching_claims"][0]["agent"] == "Codex 7"


def test_router_classifies_benchmark_lane(tmp_path: Path) -> None:
    payload = mod.classify_task(
        summary="Run snake benchmark",
        paths=["output/benchmarks/snake/run-1/thomas/index.html"],
        edit_intent=True,
        benchmark_mode=True,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
    )

    assert payload["lane"] == "benchmark"
    assert payload["flags"]["benchmark_mode"] is True
    assert "docs/ai/CHECKLISTS/agent-lane-benchmark.md" in payload["required_reads"]


def test_build_startup_payload_includes_preflight(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mod.agent_preflight,
        "evaluate_preflight",
        lambda **_: {
            "status": "degraded",
            "summary": "1 degraded, 2 ok",
            "checks": [
                {
                    "id": "rg",
                    "status": "degraded",
                    "message": "ripgrep unavailable",
                    "user_action": "Install rg.",
                }
            ],
            "policy": {
                "summary": "Tell the user the environment is degraded before using slower or lower-confidence fallbacks.",
                "can_edit": True,
                "report_before_fallback": True,
                "stop_before_edit": False,
            },
            "root": str(mod.ROOT),
            "cwd": str(mod.ROOT),
        },
    )

    payload = mod.build_startup_payload(
        summary="Patch a small bug",
        paths=["thomas/core/config.py"],
        edit_intent=True,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=_write_workboard(tmp_path),
        cwd=mod.ROOT,
    )

    assert payload["lane"] == "simple-edit"
    assert payload["preflight"]["status"] == "degraded"
    assert payload["preflight"]["policy"]["report_before_fallback"] is True
    assert payload["gate_handling"]["auto_remediate"]
    assert payload["gate_handling"]["hard_stop"]


def test_router_text_output_surfaces_preflight(tmp_path: Path) -> None:
    payload = {
        "lane": "simple-edit",
        "workflow_mode": "guided",
        "edit_intent": True,
        "workboard_required": True,
        "workboard": {
            "path": str(tmp_path / "WORKBOARD.md"),
            "active_claims": 0,
            "matching_claims": [],
            "claim_conflict": False,
            "stale": False,
            "updated_at": "2026-03-18",
        },
        "bootstrap_command": 'python scripts/crew/brief/bootstrap_claim.py --agent "<agent-id>" --scope "thomas/core/config.py" --task "Patch a small bug" --no-auto-dispatch',
        "gate_handling": {
            "summary": "Structural/quality gates should trigger remediation and retry; integrity/ownership/security gates remain hard stops.",
            "auto_remediate": ["monolith_guard"],
            "hard_stop": ["protected_files"],
        },
        "flags": {
            "ui_proof": False,
            "benchmark_mode": False,
            "tracked_work": False,
            "multi_agent": False,
            "long_running": False,
            "risky_paths": [],
        },
        "paths": ["thomas/core/config.py"],
        "required_reads": ["docs/AGENT_FILE_EDITING_RULES.md"],
        "required_checks": ["Run focused regression tests for changed behavior."],
        "escalation_triggers": ["Scope expands beyond a small isolated change."],
        "preflight": {
            "status": "degraded",
            "summary": "1 degraded, 3 ok",
            "checks": [
                {
                    "id": "cwd",
                    "status": "degraded",
                    "message": "Current working directory is outside repo root.",
                    "user_action": "Start commands from the repo root.",
                }
            ],
            "policy": {
                "summary": "Tell the user the environment is degraded before using slower or lower-confidence fallbacks.",
                "can_edit": True,
                "report_before_fallback": True,
                "stop_before_edit": False,
            },
            "root": str(mod.ROOT),
            "cwd": "C:/Windows/System32",
        },
    }

    text = mod._text_output(payload)

    assert "preflight_status: degraded" in text
    assert (
        "preflight_policy: Tell the user the environment is degraded before using slower or lower-confidence fallbacks."
        in text
    )
    assert "preflight_checks:" in text
    assert "bootstrap_command:" in text
    assert "gate_handling:" in text
    assert "auto_remediate_gates:" in text
    assert "hard_stop_gates:" in text


def test_router_text_output_surfaces_unread_inbox() -> None:
    payload = {
        "lane": "chat",
        "workflow_mode": "guided",
        "edit_intent": False,
        "workboard_required": False,
        "workboard": {
            "path": "plans/thomas/WORKBOARD.md",
            "active_claims": 0,
            "matching_claims": [],
            "claim_conflict": False,
            "stale": False,
            "updated_at": "2026-06-02",
        },
        "bootstrap_command": "",
        "gate_handling": {},
        "flags": {
            "ui_proof": False,
            "benchmark_mode": False,
            "tracked_work": False,
            "multi_agent": False,
            "long_running": False,
            "risky_paths": [],
        },
        "paths": [],
        "required_reads": [],
        "required_checks": [],
        "escalation_triggers": [],
        "preflight": {},
        "inbox": {
            "ok": True,
            "agent": "codex",
            "unread_count": 1,
            "messages": [
                {
                    "msg_id": "msg-1",
                    "from": "claude",
                    "priority": "p0",
                    "summary": "stop before touching scripts",
                    "escalation": "stale_p0",
                }
            ],
        },
    }

    text = mod._text_output(payload)

    assert "inbox: agent=codex; unread=1" in text
    assert "msg-1: from=claude priority=p0 ESCALATED; stop before touching scripts" in text
    assert "inbox_action: python scripts/crew/workboard/message.py --inbox --agent codex" in text


def test_router_text_output_surfaces_current_thread_context() -> None:
    payload = {
        "lane": "chat",
        "workflow_mode": "guided",
        "edit_intent": False,
        "workboard_required": False,
        "workboard": {
            "path": "plans/thomas/WORKBOARD.md",
            "active_claims": 0,
            "matching_claims": [],
            "claim_conflict": False,
            "stale": False,
            "updated_at": "2026-06-02",
        },
        "bootstrap_command": "",
        "gate_handling": {},
        "flags": {
            "ui_proof": False,
            "benchmark_mode": False,
            "tracked_work": False,
            "multi_agent": False,
            "long_running": False,
            "risky_paths": [],
        },
        "paths": [],
        "required_reads": [],
        "required_checks": [],
        "escalation_triggers": [],
        "preflight": {},
        "inbox": {
            "ok": True,
            "agent": "codex",
            "unread_count": 0,
            "messages": [],
        },
        "current_thread": {
            "ok": True,
            "agent": "codex",
            "peer": "claude",
            "message_count": 2,
            "awaiting_me": 0,
            "awaiting_peer": 1,
            "messages": [
                {
                    "msg_id": "msg-review",
                    "direction": "outgoing",
                    "awaiting": "peer",
                    "state": "open",
                    "summary": "waiting on Claude review",
                },
                {
                    "msg_id": "msg-context",
                    "direction": "incoming",
                    "awaiting": "thread",
                    "state": "acked",
                    "summary": "acked but relevant context",
                },
            ],
        },
    }

    text = mod._text_output(payload)

    assert "current_thread: agent=codex; peer=claude; active=2; awaiting_me=0; awaiting_peer=1" in text
    assert "msg-review: outgoing awaiting=peer state=open; waiting on Claude review" in text
    assert "msg-context: incoming awaiting=thread state=acked; acked but relevant context" in text
    assert (
        "current_thread_action: python scripts/crew/workboard/message.py --current --agent codex --peer claude" in text
    )


def test_router_text_output_surfaces_message_audit_warnings() -> None:
    payload = {
        "lane": "chat",
        "workflow_mode": "guided",
        "edit_intent": False,
        "workboard_required": False,
        "workboard": {
            "path": "plans/thomas/WORKBOARD.md",
            "active_claims": 0,
            "matching_claims": [],
            "claim_conflict": False,
            "stale": False,
            "updated_at": "2026-06-02",
        },
        "bootstrap_command": "",
        "gate_handling": {},
        "flags": {
            "ui_proof": False,
            "benchmark_mode": False,
            "tracked_work": False,
            "multi_agent": False,
            "long_running": False,
            "risky_paths": [],
        },
        "paths": [],
        "required_reads": [],
        "required_checks": [],
        "escalation_triggers": [],
        "preflight": {},
        "inbox": {
            "ok": True,
            "agent": "codex",
            "unread_count": 0,
            "messages": [],
        },
        "current_thread": {
            "ok": True,
            "agent": "codex",
            "peer": "claude",
            "message_count": 0,
            "awaiting_me": 0,
            "awaiting_peer": 0,
            "messages": [],
        },
        "message_audit": {
            "ok": False,
            "problem_count": 1,
            "canonical_inbox_count": 0,
            "canonical_current_count": 0,
            "awaiting_me": 0,
            "awaiting_peer": 0,
            "diagnosis": "message section contains noncanonical agent mentions that inbox/current views ignore",
            "parse_errors": [],
            "candidate_mentions": [
                {
                    "line": 52,
                    "text": "Claude -> Codex: waiting for your reply.",
                }
            ],
        },
    }

    text = mod._text_output(payload)

    assert "message_audit: warning; problems=1; inbox=0; current=0" in text
    assert "candidate_mention line 52: Claude -> Codex: waiting for your reply." in text


def test_router_text_output_trims_long_current_thread_summaries() -> None:
    long_summary = "Claude coordination context " * 20
    payload = {
        "lane": "chat",
        "workflow_mode": "guided",
        "edit_intent": False,
        "workboard_required": False,
        "workboard": {
            "path": "plans/thomas/WORKBOARD.md",
            "active_claims": 0,
            "matching_claims": [],
            "claim_conflict": False,
            "stale": False,
            "updated_at": "2026-06-02",
        },
        "bootstrap_command": "",
        "gate_handling": {},
        "flags": {
            "ui_proof": False,
            "benchmark_mode": False,
            "tracked_work": False,
            "multi_agent": False,
            "long_running": False,
            "risky_paths": [],
        },
        "paths": [],
        "required_reads": [],
        "required_checks": [],
        "escalation_triggers": [],
        "preflight": {},
        "inbox": {
            "ok": True,
            "agent": "codex",
            "unread_count": 0,
            "messages": [],
        },
        "current_thread": {
            "ok": True,
            "agent": "codex",
            "message_count": 1,
            "awaiting_me": 0,
            "awaiting_peer": 1,
            "messages": [
                {
                    "msg_id": "msg-long",
                    "direction": "outgoing",
                    "awaiting": "peer",
                    "state": "open",
                    "summary": long_summary,
                }
            ],
        },
    }

    text = mod._text_output(payload)

    assert "msg-long: outgoing awaiting=peer state=open; Claude coordination context" in text
    assert long_summary not in text
    assert "..." in text
