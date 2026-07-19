"""Executable evidence probes for the ChatGPT capability parity rubric."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chatgpt_parity_artifact_probes import (
    TERMINAL_DELEGATION_STATES,
    delegation_summaries,
    map_artifact_executions,
)
from chatgpt_parity_artifact_probes import (
    matrix_browser_interactions as _matrix_browser_interactions,
)
from chatgpt_parity_conversation_probe import run_benign_token_probe, run_conversation_probe
from chatgpt_parity_conversation_probe import web_source_conflict_probe as _web_source_conflict_probe
from chatgpt_parity_data_probes import data_code_chart_probe as _data_code_chart_probe
from chatgpt_parity_data_probes import data_dirty_formula_sandbox_probe as _data_dirty_formula_sandbox_probe
from chatgpt_parity_document_probes import (
    document_conflict_truncation_grounding_probe as _document_conflict_truncation_grounding_probe,
)
from chatgpt_parity_document_probes import (
    document_upload_grounded_artifact_probe as _document_upload_grounded_artifact_probe,
)
from chatgpt_parity_document_probes import project_workspace_lifecycle_probe as _project_workspace_lifecycle_probe
from chatgpt_parity_harness import EvidenceRow, record_delegation_runtime, record_model_runtime_event
from chatgpt_parity_image_probes import canvas_revision_integrity_probe as _canvas_revision_integrity_probe
from chatgpt_parity_image_probes import (
    image_understanding_generation_edit_probe as _image_understanding_generation_edit_probe,
)
from chatgpt_parity_image_probes import (
    image_visual_injection_edit_fidelity_probe as _image_visual_injection_edit_fidelity_probe,
)
from chatgpt_parity_memory_probes import (
    memory_correction_deletion_isolation_probe as _memory_correction_deletion_isolation_probe,
)
from chatgpt_parity_memory_probes import (
    privacy_remanence_isolation_lockdown_probe as _privacy_remanence_isolation_lockdown_probe,
)
from chatgpt_parity_privacy_project_probes import (
    privacy_export_delete_temporary_probe as _privacy_export_delete_temporary_probe,
)
from chatgpt_parity_privacy_project_probes import (
    project_isolation_stale_share_probe as _project_isolation_stale_share_probe,
)
from chatgpt_parity_runtime_action_probes import (
    scheduled_recovery_dedup_noise_probe as _scheduled_recovery_dedup_noise_probe,
)
from chatgpt_parity_runtime_action_probes import scheduled_task_lifecycle_probe as _scheduled_task_lifecycle_probe
from chatgpt_parity_runtime_probes import (
    agentic_interrupt_approval_recovery_probe as _agentic_interrupt_approval_recovery_probe,
)
from chatgpt_parity_runtime_probes import (
    connected_app_adversarial_controls_probe as _connected_app_adversarial_controls_probe,
)
from chatgpt_parity_runtime_probes import connected_app_receipt_probe as _connected_app_receipt_probe
from chatgpt_parity_runtime_probes import (
    custom_assistant_plugin_adversarial_probe as _custom_assistant_plugin_adversarial_probe,
)
from chatgpt_parity_runtime_probes import (
    custom_assistant_plugin_lifecycle_probe as _custom_assistant_plugin_lifecycle_probe,
)
from chatgpt_parity_runtime_voice_probes import voice_audio_roundtrip_probe as _voice_audio_roundtrip_probe
from chatgpt_parity_runtime_voice_probes import (
    voice_noise_language_interrupt_latency_probe as _voice_noise_language_interrupt_latency_probe,
)


@dataclass
class ProbeContext:
    repo_root: Path
    base_url: str
    profile: str
    model_id: str
    run_tests: bool
    timeout_seconds: float = 120.0
    command_cache: dict[tuple[str, ...], tuple[int, str]] = field(default_factory=dict)
    tools_cache: list[str] | None = None
    runtime_cache: dict[str, Any] = field(default_factory=dict)


def _http_json(ctx: ProbeContext, path: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        ctx.base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=ctx.timeout_seconds) as response:
            return int(response.status), json.load(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:1000]}
        return int(exc.code), payload


def _http_text(ctx: ProbeContext, path: str) -> tuple[int, str]:
    request = urllib.request.Request(ctx.base_url.rstrip("/") + path, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=ctx.timeout_seconds) as response:
            return int(response.status), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")


def _chat(ctx: ProbeContext, session_id: str, message: str) -> tuple[str, list[str]]:
    payload = {
        "message": message,
        "session_id": session_id,
        "profile": ctx.profile,
        "model": ctx.profile,
        "model_id": ctx.model_id,
        "autonomy_level": 1,
        "file_access": "read_only",
        "token_economy": "optimal",
        "reasoning_effort": "medium",
        "memory": True,
        "docs": [],
        "images": [],
    }
    request = urllib.request.Request(
        ctx.base_url.rstrip("/") + "/api/v2/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    text_parts: list[str] = []
    errors: list[str] = []
    with urllib.request.urlopen(request, timeout=ctx.timeout_seconds) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            event = json.loads(line)
            if event.get("type") == "text":
                text_parts.append(str(event.get("text") or ""))
            elif event.get("type") == "error":
                errors.append(str(event.get("error") or "unknown error"))
            record_model_runtime_event(ctx, event)
    return "".join(text_parts).strip(), errors


def _new_session(ctx: ProbeContext) -> str:
    status, payload = _http_json(ctx, "/api/session/new", method="POST")
    if status != 200 or not isinstance(payload, dict) or not payload.get("session_id"):
        raise RuntimeError(f"session creation failed: HTTP {status} {payload!r}")
    return str(payload["session_id"])


def _conversation_probe(ctx: ProbeContext, *, adversarial: bool) -> tuple[bool, str]:
    return run_conversation_probe(
        ctx,
        adversarial=adversarial,
        new_session=_new_session,
        chat=_chat,
        http_json=_http_json,
    )


def _benign_token_probe(ctx: ProbeContext) -> tuple[bool, str]:
    return run_benign_token_probe(ctx, new_session=_new_session, chat=_chat)


def _web_search_probe(ctx: ProbeContext) -> tuple[bool, str]:
    session_id = _new_session(ctx)
    payload = {
        "message": (
            "Use web.search now to find the newest entry on OpenAI's official ChatGPT release notes. "
            "Answer with the date and at least one source URL. This is read-only research and does not "
            "require higher autonomy."
        ),
        "session_id": session_id,
        "profile": ctx.profile,
        "model": ctx.profile,
        "model_id": ctx.model_id,
        "autonomy_level": 1,
        "file_access": "read_only",
        "token_economy": "optimal",
        "reasoning_effort": "medium",
        "memory": True,
        "docs": [],
        "images": [],
    }
    request = urllib.request.Request(
        ctx.base_url.rstrip("/") + "/api/v2/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    events: list[dict[str, Any]] = []
    with urllib.request.urlopen(request, timeout=ctx.timeout_seconds) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                event = json.loads(line)
                if isinstance(event, dict):
                    events.append(event)
                    record_model_runtime_event(ctx, event)

    text = "".join(str(event.get("text") or "") for event in events if event.get("type") == "text").strip()
    errors = [str(event.get("error") or "") for event in events if event.get("type") == "error"]
    receipts = [event for event in events if event.get("type") == "tool_result" and event.get("name") == "web.search"]
    receipt_ok = any(bool(event.get("ok")) and "web.fetch" in list(event.get("calls") or []) for event in receipts)
    month = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    has_date = bool(re.search(rf"\b{month}\s+\d{{1,2}},\s+\d{{4}}\b", text, re.I))
    has_url = bool(re.search(r"https?://[^\s)\]]+", text))
    leaked_json = bool(re.search(r"[\"']name[\"']\s*:\s*[\"']web[._]search", text, re.I))
    opaque = "sorry" in text.lower() or "trouble with that" in text.lower()
    delegated = any(event.get("type") in {"task_request", "delegation_started"} for event in events)
    passed = receipt_ok and has_date and has_url and not leaked_json and not opaque and not delegated and not errors
    actual = json.dumps(
        {
            "text": text,
            "receipt_ok": receipt_ok,
            "has_date": has_date,
            "has_url": has_url,
            "leaked_json": leaked_json,
            "delegated": delegated,
            "errors": errors,
        },
        ensure_ascii=False,
    )
    return passed, actual


def _agentic_browser_artifact_probe(ctx: ProbeContext) -> tuple[bool, str]:
    session_id = _new_session(ctx)
    prompt = (
        "Use the registered tools to complete this exact task in order:\n"
        "1. Call browser.open on https://example.com using session_id agentic-parity.\n"
        "2. Call browser.extract on that browser session with selector h1.\n"
        "3. Call fs.write_file to create agentic_report.md in your workspace. Its content must include "
        "the source URL https://example.com, the extracted heading, and one sentence explaining what the page is.\n"
        "4. Call fs.read_file on agentic_report.md to verify it.\n"
        "Do not use fs.list_dir or shell. Do not merely describe the steps. Finish only after the verified file exists."
    )
    payload = {
        "message": prompt,
        "session_id": session_id,
        "profile": ctx.profile,
        "model": ctx.profile,
        "model_id": ctx.model_id,
        "mode": "max",
        "autonomy_level": 4,
        "file_access": "workspace",
        "token_economy": "fast",
        "reasoning_effort": "low",
        "memory": True,
        "docs": [],
        "images": [],
    }
    request = urllib.request.Request(
        ctx.base_url.rstrip("/") + "/api/v2/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    events: list[dict[str, Any]] = []
    with urllib.request.urlopen(request, timeout=max(ctx.timeout_seconds, 180.0)) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                event = json.loads(line)
                if isinstance(event, dict):
                    events.append(event)
                    record_model_runtime_event(ctx, event)

    progress = {
        str(event.get("last_progress") or "").strip()
        for event in events
        if event.get("type") in {"delegation_started", "delegation_progress", "delegation_completed"}
        and str(event.get("last_progress") or "").strip()
    }
    terminal: dict[str, Any] = {}
    deadline = time.monotonic() + max(10.0, ctx.timeout_seconds)
    while time.monotonic() < deadline:
        status, body = _http_json(ctx, f"/api/v2/chat/session/{session_id}/delegations")
        rows = body.get("delegations", []) if status == 200 and isinstance(body, dict) else []
        row = rows[0] if rows and isinstance(rows[0], dict) else {}
        latest = str(row.get("last_progress") or "").strip()
        if latest:
            progress.add(latest)
        if str(row.get("state") or "").lower() in {"completed", "failed", "cancelled", "canceled"}:
            terminal = row
            break
        time.sleep(0.25)

    execution_id = str(terminal.get("execution_id") or "")
    proof = terminal.get("proof") if isinstance(terminal.get("proof"), dict) else {}
    artifacts = proof.get("artifacts", []) if isinstance(proof, dict) else []
    artifact_names = [str(item.get("name") or "") for item in artifacts if isinstance(item, dict)]
    artifact_status, artifact_text = (
        _http_text(ctx, f"/deliverable/{execution_id}/agentic_report.md") if execution_id else (0, "")
    )
    progress_text = "\n".join(sorted(progress)).lower()
    required_progress = ["browser.open", "browser.extract", "fs.write_file", "fs.read_file"]
    receipt = terminal.get("receipt") if isinstance(terminal.get("receipt"), dict) else {}
    model_runtime_ok = record_delegation_runtime(ctx, terminal)
    opaque = "sorry" in artifact_text.lower() or "trouble with that" in artifact_text.lower()
    placeholders = bool(re.search(r"\[(?:insert|heading|title|description|content)\b", artifact_text, re.I))
    passed = bool(
        terminal.get("state") == "completed"
        and terminal.get("proof_status") == "verified"
        and receipt.get("ok") is True
        and model_runtime_ok
        and "agentic_report.md" in artifact_names
        and artifact_status == 200
        and "https://example.com" in artifact_text
        and "Example Domain" in artifact_text
        and not placeholders
        and not opaque
        and len(progress) >= 4
        and all(name in progress_text for name in required_progress)
    )
    actual = json.dumps(
        {
            "session_id": session_id,
            "execution_id": execution_id,
            "state": terminal.get("state"),
            "proof_status": terminal.get("proof_status"),
            "receipt_ok": receipt.get("ok"),
            "model_runtime_ok": model_runtime_ok,
            "artifact_names": artifact_names,
            "artifact_status": artifact_status,
            "artifact_text": artifact_text[:1000],
            "progress": sorted(progress),
            "required_progress": required_progress,
            "placeholders": placeholders,
            "opaque_fallback": opaque,
        },
        ensure_ascii=False,
    )
    return passed, actual


def _canvas_artifact_matrix_probe(ctx: ProbeContext) -> tuple[bool, str]:
    session_id = _new_session(ctx)
    prompt = (
        "Create exactly these four openable artifacts as four separate deliverables in four separate task "
        "workspaces. Use fs.write_file and then "
        "fs.read_file to verify each one:\n"
        '1. parity_document.md: a Markdown document with heading "Thomas Artifact Matrix" and sentence '
        '"DOCUMENT-MARKER-170".\n'
        "2. parity_sheet.csv: a spreadsheet with header Item,Value and rows Alpha,17 and Beta,23.\n"
        "3. parity_slides.html: a self-contained HTML presentation with exactly three visible slide sections "
        'labelled "Slide 1", "Slide 2", and "Slide 3", '
        'title "Thomas Parity Deck", visible text "SLIDES-MARKER-170", and Previous/Next buttons that change the '
        "visible slide.\n"
        '4. index.html: a self-contained interactive site titled "Thomas Interactive Site", visible text '
        '"SITE-MARKER-170", and a button with id action-button that changes an element with id status-text '
        'from "Ready" to "Working" when clicked.\n'
        "Do not use shell. Do not merely describe the files. Use the exact filenames, read back all four, "
        "and finish only after they exist."
    )
    payload = {
        "message": prompt,
        "session_id": session_id,
        "profile": ctx.profile,
        "model": ctx.profile,
        "model_id": ctx.model_id,
        "mode": "max",
        "autonomy_level": 4,
        "file_access": "workspace",
        "token_economy": "fast",
        "reasoning_effort": "low",
        "memory": True,
        "docs": [],
        "images": [],
    }
    request = urllib.request.Request(
        ctx.base_url.rstrip("/") + "/api/v2/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    events: list[dict[str, Any]] = []
    with urllib.request.urlopen(request, timeout=max(ctx.timeout_seconds, 180.0)) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                event = json.loads(line)
                if isinstance(event, dict):
                    events.append(event)
                    record_model_runtime_event(ctx, event)

    rows: list[dict[str, Any]] = []
    execution_ids: dict[str, str] = {}
    owners: dict[str, dict[str, Any]] = {}
    ambiguous: list[str] = []
    expected = {
        "parity_document.md": ["Thomas Artifact Matrix", "DOCUMENT-MARKER-170"],
        "parity_sheet.csv": ["Item,Value", "Alpha,17", "Beta,23"],
        "parity_slides.html": ["Thomas Parity Deck", "SLIDES-MARKER-170", "Slide 1", "Slide 2", "Slide 3"],
        "index.html": ["Thomas Interactive Site", "SITE-MARKER-170", "action-button", "status-text"],
    }
    deadline = time.monotonic() + max(10.0, ctx.timeout_seconds)
    while time.monotonic() < deadline:
        status, body = _http_json(ctx, f"/api/v2/chat/session/{session_id}/delegations")
        candidates = body.get("delegations", []) if status == 200 and isinstance(body, dict) else []
        rows = [row for row in candidates if isinstance(row, dict)]
        execution_ids, owners, ambiguous = map_artifact_executions(rows, expected)
        mapped_terminal = set(execution_ids) == set(expected) and all(
            str(owners[name].get("state") or "").lower() in TERMINAL_DELEGATION_STATES for name in expected
        )
        group_terminal = len(rows) >= len(expected) and all(
            str(row.get("state") or "").lower() in TERMINAL_DELEGATION_STATES for row in rows
        )
        if mapped_terminal or group_terminal:
            break
        time.sleep(0.25)

    separate_workspaces = len(set(execution_ids.values())) == len(expected)
    artifact_results: dict[str, Any] = {}
    contents: dict[str, str] = {}
    all_content_ok = set(execution_ids) == set(expected)
    for name, required in expected.items():
        execution_id = execution_ids.get(name, "")
        status, content = _http_text(ctx, f"/deliverable/{execution_id}/{name}") if execution_id else (0, "")
        contents[name] = content
        missing = [literal for literal in required if literal not in content]
        artifact_results[name] = {
            "execution_id": execution_id,
            "status": status,
            "bytes": len(content.encode("utf-8")),
            "missing": missing,
        }
        all_content_ok = all_content_ok and status == 200 and not missing

    terminal_rows = [owners[name] for name in expected if name in owners]
    last_progress = [str(row.get("last_progress") or "") for row in terminal_rows]
    pending_language = bool(
        any(
            re.search(
                r"\b(?:please wait|once (?:the|these) checks? pass|let me (?:execute|run|finish))\b",
                progress,
                re.I,
            )
            for progress in last_progress
        )
    )
    terminal_verified = len(terminal_rows) == len(expected) and all(
        row.get("state") == "completed"
        and row.get("proof_status") == "verified"
        and isinstance(row.get("receipt"), dict)
        and row["receipt"].get("ok") is True
        for row in terminal_rows
    )
    model_runtime_results = [record_delegation_runtime(ctx, row) for row in terminal_rows]
    worker_models_verified = len(model_runtime_results) == len(expected) and all(model_runtime_results)
    interaction_ok = False
    interaction: dict[str, Any] = {}
    if (
        terminal_verified
        and worker_models_verified
        and not ambiguous
        and separate_workspaces
        and all_content_ok
        and not pending_language
    ):
        interaction_ok, interaction = asyncio.run(_matrix_browser_interactions(ctx, execution_ids))

    passed = bool(
        terminal_verified
        and worker_models_verified
        and not ambiguous
        and separate_workspaces
        and all_content_ok
        and interaction_ok
        and not pending_language
    )
    if passed:
        ctx.runtime_cache["canvas_artifact_matrix"] = {
            "session_id": session_id,
            "execution_ids": execution_ids,
            "contents": contents,
        }
    actual = json.dumps(
        {
            "session_id": session_id,
            "execution_ids": execution_ids,
            "separate_workspaces": separate_workspaces,
            "ambiguous_artifacts": ambiguous,
            "delegations": delegation_summaries(rows),
            "terminal_verified": terminal_verified,
            "worker_models_verified": worker_models_verified,
            "artifacts": artifact_results,
            "interaction": interaction,
            "last_progress": last_progress,
            "pending_language": pending_language,
        },
        ensure_ascii=False,
    )
    return passed, actual


def _memory_cross_session_probe(ctx: ProbeContext) -> tuple[bool, str]:
    """Prove chat-captured preference recall in a new chat without leaving test memory behind."""
    key = "user.preference"
    marker = f"PARITY-MEMORY-{int(time.time() * 1000)}"
    status, before = _http_json(ctx, "/api/memory")
    before_pins = before.get("pins", []) if status == 200 and isinstance(before, dict) else []
    original = next(
        (
            str(item.get("text") or "")
            for item in before_pins
            if isinstance(item, dict) and str(item.get("key") or "") == key
        ),
        None,
    )
    first_text = ""
    recall_text = ""
    first_errors: list[str] = []
    recall_errors: list[str] = []
    observed_pin = ""
    cleanup_ok = False
    purged_rows: dict[str, int] = {}
    try:
        first_text, first_errors = _chat(
            ctx,
            _new_session(ctx),
            f"I prefer {marker}. Remember that preference for later. Reply exactly: MEMORY-SAVED.",
        )
        after_status, after = _http_json(ctx, "/api/memory")
        after_pins = after.get("pins", []) if after_status == 200 and isinstance(after, dict) else []
        observed_pin = next(
            (
                str(item.get("text") or "")
                for item in after_pins
                if isinstance(item, dict) and str(item.get("key") or "") == key
            ),
            "",
        )
        recall_text, recall_errors = _chat(
            ctx,
            _new_session(ctx),
            "What preference did I tell you? Reply with the exact remembered preference and no other words.",
        )
    finally:
        if original:
            _http_json(ctx, "/api/memory/pins", method="POST", body={"key": key, "text": original})
        else:
            encoded = urllib.parse.quote(key, safe="")
            _http_json(ctx, f"/api/memory/pins/{encoded}", method="DELETE")
        v2_health = before.get("v2_health", {}) if isinstance(before, dict) else {}
        db_path_text = str(v2_health.get("db_path") or "") if isinstance(v2_health, dict) else ""
        db_path = Path(db_path_text) if db_path_text else Path()
        cleanup_ok = not db_path_text
        if db_path.is_file():
            connection = sqlite3.connect(db_path, timeout=10)
            try:
                connection.execute("BEGIN IMMEDIATE")
                cleanup_statements = {
                    "retrieval_traces": (
                        "DELETE FROM retrieval_traces WHERE query LIKE ? OR results_json LIKE ?",
                        (f"%{marker}%", f"%{marker}%"),
                    ),
                    "packs": ("DELETE FROM packs WHERE text LIKE ?", (f"%{marker}%",)),
                    "pins": (
                        "DELETE FROM pins WHERE ref_id LIKE ? OR note LIKE ?",
                        (f"%{marker}%", f"%{marker}%"),
                    ),
                    "profile_hints": ("DELETE FROM profile_hints WHERE value LIKE ?", (f"%{marker}%",)),
                    "semantic_facts": (
                        "DELETE FROM semantic_facts WHERE subject LIKE ? OR predicate LIKE ? OR obj LIKE ?",
                        (f"%{marker}%", f"%{marker}%", f"%{marker}%"),
                    ),
                    "episodes": ("DELETE FROM episodes WHERE content LIKE ?", (f"%{marker}%",)),
                }
                for table, (statement, values) in cleanup_statements.items():
                    purged_rows[table] = int(connection.execute(statement, values).rowcount)
                connection.commit()
                remaining = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM episodes WHERE content LIKE ?",
                        (f"%{marker}%",),
                    ).fetchone()[0]
                )
                cleanup_ok = remaining == 0
            except sqlite3.Error:
                connection.rollback()
                raise
            finally:
                connection.close()
        cleanup_status, cleanup = _http_json(ctx, "/api/memory")
        cleanup_pins = cleanup.get("pins", []) if cleanup_status == 200 and isinstance(cleanup, dict) else []
        cleanup_ok = cleanup_ok and not any(
            isinstance(item, dict) and marker in str(item.get("text") or "") for item in cleanup_pins
        )

    opaque = "sorry, i had trouble with that" in (first_text + " " + recall_text).lower()
    passed = bool(
        "MEMORY-SAVED" in first_text
        and marker in recall_text
        and not first_errors
        and not recall_errors
        and not opaque
        and cleanup_ok
    )
    actual = json.dumps(
        {
            "first": first_text,
            "observed_pin": observed_pin,
            "recall": recall_text,
            "errors": first_errors + recall_errors,
            "opaque_fallback": opaque,
            "cleanup_ok": cleanup_ok,
            "purged_rows": purged_rows,
            "restored_prior_value": original is not None,
        },
        ensure_ascii=False,
    )
    return passed, actual


def _tool_names(ctx: ProbeContext) -> list[str]:
    if ctx.tools_cache is not None:
        return ctx.tools_cache
    status, payload = _http_json(ctx, "/api/tools")
    tools = payload.get("tools", []) if status == 200 and isinstance(payload, dict) else []
    ctx.tools_cache = [str(tool.get("name") or tool.get("id") or "") for tool in tools if isinstance(tool, dict)]
    return ctx.tools_cache


def _run_command(ctx: ProbeContext, argv: list[str]) -> tuple[int, str]:
    key = tuple(str(item) for item in argv)
    if key not in ctx.command_cache:
        completed = subprocess.run(  # noqa: S603 - argv comes from the committed rubric
            key,
            cwd=ctx.repo_root,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        output = (completed.stdout + "\n" + completed.stderr).strip()[-4000:]
        ctx.command_cache[key] = (completed.returncode, output)
    return ctx.command_cache[key]


def evaluate_check(family: str, tier: int, index: int, check: dict[str, Any], ctx: ProbeContext) -> EvidenceRow:
    kind = str(check.get("kind") or "")
    severity = str(check.get("severity") or "med")
    case = f"{family}.tier{tier}.{index + 1}.{kind or 'unknown'}"
    passed = False
    expected = kind
    actual = ""
    evidence = ""
    try:
        if kind == "path_exists_any":
            paths = [str(path) for path in check.get("paths", [])]
            found = [path for path in paths if (ctx.repo_root / path).exists()]
            expected = "at least one declared runtime path exists"
            actual = json.dumps(found)
            passed = bool(found)
        elif kind == "path_contains":
            rel = str(check.get("path") or "")
            needles = [str(needle) for needle in check.get("needles", [])]
            target = ctx.repo_root / rel
            content = target.read_text(encoding="utf-8") if target.is_file() else ""
            missing = [needle for needle in needles if needle not in content]
            expected = f"{rel} contains all declared contracts"
            actual = "missing=" + json.dumps(missing)
            passed = target.is_file() and not missing
            evidence = rel
        elif kind == "tools_any":
            patterns = [str(pattern).lower() for pattern in check.get("patterns", [])]
            matches = [name for name in _tool_names(ctx) if any(pattern in name.lower() for pattern in patterns)]
            minimum = int(check.get("minimum") or 1)
            expected = f"at least {minimum} registered tools match {patterns}"
            actual = json.dumps(matches[:30])
            passed = len(matches) >= minimum
            evidence = "/api/tools"
        elif kind == "api_json":
            path = str(check.get("path") or "")
            status, payload = _http_json(ctx, path)
            required = [str(key) for key in check.get("required_keys", [])]
            missing = [key for key in required if not isinstance(payload, dict) or key not in payload]
            expected = f"GET {path} returns HTTP 200 JSON with keys {required}"
            actual = f"HTTP {status}; missing={missing}; payload={str(payload)[:1000]}"
            passed = status == 200 and isinstance(payload, (dict, list)) and not missing
            evidence = path
        elif kind == "command":
            argv = [str(item) for item in check.get("argv", [])]
            expected = "command exits 0: " + " ".join(argv)
            if not ctx.run_tests:
                actual = "not run; pass --run-tests"
            else:
                returncode, output = _run_command(ctx, argv)
                actual = f"exit={returncode}; {output}"
                passed = returncode == 0
                evidence = " ".join(argv)
        elif kind == "live_probe":
            probe = str(check.get("probe") or "")
            expected = f"live probe {probe} passes"
            if probe == "conversation_multi_turn":
                passed, actual = _conversation_probe(ctx, adversarial=False)
            elif probe == "conversation_adversarial_followup":
                passed, actual = _conversation_probe(ctx, adversarial=True)
            elif probe == "conversation_benign_token_refusal":
                passed, actual = _benign_token_probe(ctx)
            elif probe == "web_search_cited_answer":
                passed, actual = _web_search_probe(ctx)
            elif probe == "web_source_conflict":
                passed, actual = _web_source_conflict_probe(ctx)
            elif probe == "agentic_browser_artifact":
                passed, actual = _agentic_browser_artifact_probe(ctx)
            elif probe == "agentic_interrupt_approval_recovery":
                passed, actual = _agentic_interrupt_approval_recovery_probe(ctx)
            elif probe == "canvas_artifact_matrix":
                passed, actual = _canvas_artifact_matrix_probe(ctx)
            elif probe == "canvas_revision_integrity":
                passed, actual = _canvas_revision_integrity_probe(ctx)
            elif probe == "data_code_chart_roundtrip":
                passed, actual = _data_code_chart_probe(ctx)
            elif probe == "data_dirty_formula_sandbox":
                passed, actual = _data_dirty_formula_sandbox_probe(ctx)
            elif probe == "document_upload_grounded_artifact":
                passed, actual = _document_upload_grounded_artifact_probe(ctx)
            elif probe == "document_conflict_truncation_grounding":
                passed, actual = _document_conflict_truncation_grounding_probe(ctx)
            elif probe == "image_understanding_generation_edit":
                passed, actual = _image_understanding_generation_edit_probe(ctx)
            elif probe == "image_visual_injection_edit_fidelity":
                passed, actual = _image_visual_injection_edit_fidelity_probe(ctx)
            elif probe == "memory_cross_session_recall":
                passed, actual = _memory_cross_session_probe(ctx)
            elif probe == "memory_correction_deletion_isolation":
                passed, actual = _memory_correction_deletion_isolation_probe(ctx)
            elif probe == "scheduled_task_lifecycle":
                passed, actual = _scheduled_task_lifecycle_probe(ctx)
            elif probe == "scheduled_recovery_dedup_noise":
                passed, actual = _scheduled_recovery_dedup_noise_probe(ctx)
            elif probe == "connected_app_receipt":
                passed, actual = _connected_app_receipt_probe(ctx)
            elif probe == "connected_app_adversarial_controls":
                passed, actual = _connected_app_adversarial_controls_probe(ctx)
            elif probe == "custom_assistant_plugin_lifecycle":
                passed, actual = _custom_assistant_plugin_lifecycle_probe(ctx)
            elif probe == "custom_assistant_plugin_adversarial":
                passed, actual = _custom_assistant_plugin_adversarial_probe(ctx)
            elif probe == "privacy_export_delete_temporary":
                passed, actual = _privacy_export_delete_temporary_probe(ctx)
            elif probe == "privacy_remanence_isolation_lockdown":
                passed, actual = _privacy_remanence_isolation_lockdown_probe(ctx)
            elif probe == "project_workspace_lifecycle":
                passed, actual = _project_workspace_lifecycle_probe(ctx)
            elif probe == "project_isolation_stale_share":
                passed, actual = _project_isolation_stale_share_probe(ctx)
            elif probe == "voice_audio_roundtrip":
                passed, actual = _voice_audio_roundtrip_probe(ctx)
            elif probe == "voice_noise_language_interrupt_latency":
                passed, actual = _voice_noise_language_interrupt_latency_probe(ctx)
            else:
                actual = f"unimplemented live probe: {probe}"
            evidence = ctx.base_url
        elif kind == "manual":
            expected = "executable evidence exists"
            actual = str(check.get("reason") or "manual evidence is not accepted")
        else:
            expected = "known executable check kind"
            actual = f"unknown check kind: {kind!r}"
    except (OSError, RuntimeError, TimeoutError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        actual = f"{type(exc).__name__}: {exc}"
        passed = False
    return EvidenceRow(family, tier, case, expected, actual, passed, severity, evidence)


def collect_evidence(rubric: dict[str, Any], ctx: ProbeContext) -> list[EvidenceRow]:
    rows: list[EvidenceRow] = []
    for family in rubric["families"]:
        for tier in (1, 2, 3, 4):
            for index, check in enumerate(family["tiers"][str(tier)]):
                rows.append(evaluate_check(family["id"], tier, index, check, ctx))
    return rows
