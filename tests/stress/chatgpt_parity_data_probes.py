"""Adversarial data, spreadsheet, chart, and sandbox probes."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from chatgpt_parity_harness import record_delegation_runtime, record_model_runtime_event


def _new_session_id(ctx: Any) -> str:
    request = urllib.request.Request(ctx.base_url.rstrip("/") + "/api/session/new", data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=ctx.timeout_seconds) as response:
        payload = json.load(response)
    session_id = str(payload.get("session_id") or "") if isinstance(payload, dict) else ""
    if not session_id:
        raise RuntimeError(f"session creation failed: {payload!r}")
    return session_id


def _http_json(ctx: Any, path: str) -> tuple[int, Any]:
    request = urllib.request.Request(ctx.base_url.rstrip("/") + path, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=ctx.timeout_seconds) as response:
            return int(response.status), json.load(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return int(exc.code), json.loads(raw)
        except json.JSONDecodeError:
            return int(exc.code), {"error": raw}


def _http_text(ctx: Any, path: str) -> tuple[int, str]:
    request = urllib.request.Request(ctx.base_url.rstrip("/") + path, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=ctx.timeout_seconds) as response:
            return int(response.status), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")


def data_code_chart_probe(ctx: Any) -> tuple[bool, str]:
    """Prove a normal-case CSV-to-analysis-to-chart turn through the live ChatGPT path."""
    session_id = _new_session_id(ctx)
    prompt = (
        "Create an interactive bar chart on the Canvas from this CSV input:\n"
        "Category,Value\nAlpha,3\nBeta,7\nGamma,5\n"
        "Use the exact visible title DATA-CHART-MARKER-56. Show every category and value, plus the exact "
        "visible analysis lines TOTAL 15 and PEAK BETA 7. Keep the chart self-contained and finish only "
        "after index.html is rendered on the Canvas."
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
        "memory": False,
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

    terminal: dict[str, Any] = {}
    deadline = time.monotonic() + max(10.0, ctx.timeout_seconds)
    while time.monotonic() < deadline:
        status, body = _http_json(ctx, f"/api/v2/chat/session/{session_id}/delegations")
        rows = body.get("delegations", []) if status == 200 and isinstance(body, dict) else []
        row = rows[0] if rows and isinstance(rows[0], dict) else {}
        if str(row.get("state") or "").lower() in {"completed", "failed", "cancelled", "canceled"}:
            terminal = row
            break
        time.sleep(0.25)

    execution_id = str(terminal.get("execution_id") or "")
    artifact_status, artifact_html = (
        _http_text(ctx, f"/deliverable/{execution_id}/index.html") if execution_id else (0, "")
    )
    required = ["DATA-CHART-MARKER-56", "Alpha", "Beta", "Gamma", "TOTAL 15", "PEAK BETA 7"]
    missing = [literal for literal in required if literal not in artifact_html]
    proof = terminal.get("proof") if isinstance(terminal.get("proof"), dict) else {}
    artifacts = proof.get("artifacts", []) if isinstance(proof, dict) else []
    artifact_names = [str(item.get("name") or "") for item in artifacts if isinstance(item, dict)]
    receipt = terminal.get("receipt") if isinstance(terminal.get("receipt"), dict) else {}
    model_runtime_ok = record_delegation_runtime(ctx, terminal)
    opaque = "sorry" in artifact_html.lower() or "trouble with that" in artifact_html.lower()
    passed = bool(
        terminal.get("state") == "completed"
        and terminal.get("proof_status") == "verified"
        and receipt.get("ok") is True
        and model_runtime_ok
        and artifact_status == 200
        and not missing
        and not opaque
    )
    return passed, json.dumps(
        {
            "session_id": session_id,
            "execution_id": execution_id,
            "state": terminal.get("state"),
            "proof_status": terminal.get("proof_status"),
            "receipt_ok": receipt.get("ok"),
            "model_runtime_ok": model_runtime_ok,
            "event_types": [str(event.get("type") or "") for event in events],
            "artifact_names": artifact_names,
            "artifact_status": artifact_status,
            "artifact_bytes": len(artifact_html.encode("utf-8")),
            "missing": missing,
            "opaque_fallback": opaque,
        },
        ensure_ascii=False,
    )


async def data_browser_interaction(ctx: Any, execution_id: str) -> tuple[bool, dict[str, Any]]:
    """Operate the audit control and inspect exact rendered chart facts."""
    from thomas.tools.browser import (
        BrowserClickTool,
        BrowserCloseTool,
        BrowserExtractTool,
        BrowserOpenTool,
        BrowserScreenshotTool,
    )

    session = f"data-adversarial-{execution_id[-12:]}"
    url = f"{ctx.base_url.rstrip('/')}/deliverable/{execution_id}/index.html"
    shot = Path.home() / ".thomas" / "proof" / f"{execution_id}-data-adversarial.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    try:
        opened = await BrowserOpenTool().execute({"url": url, "session": session})
        total = await BrowserExtractTool().execute({"selector": "#total-value", "session": session})
        peak = await BrowserExtractTool().execute({"selector": "#peak-value", "session": session})
        formula = await BrowserExtractTool().execute({"selector": "#formula-cell", "session": session})
        before = await BrowserExtractTool().execute({"selector": "#audit-state", "session": session})
        clicked = await BrowserClickTool().execute({"selector": "#audit-toggle", "session": session})
        after = await BrowserExtractTool().execute({"selector": "#audit-state", "session": session})
        audit = await BrowserExtractTool().execute({"selector": "#audit-details", "session": session})
        screenshot = await BrowserScreenshotTool().execute({"path": str(shot), "session": session})
        formula_text = "\n".join(str(item) for item in (formula.data or []))
        audit_text = "\n".join(str(item) for item in (audit.data or []))
        results = {
            "opened": opened.ok,
            "total": total.data,
            "peak": peak.data,
            "formula": formula.data,
            "audit_before": before.data,
            "clicked": clicked.ok,
            "audit_after": after.data,
            "audit_details": audit.data,
            "screenshot": str(shot) if screenshot.ok and shot.is_file() else "",
        }
        passed = bool(
            opened.ok
            and total.data == ["1460"]
            and peak.data == ["Alpha 1200"]
            and formula_text.startswith("'=")
            and before.data == ["Closed"]
            and clicked.ok
            and after.data == ["Open"]
            and all(marker in audit_text for marker in ("Excluded 2", "Merged 1", "Sanitized 1"))
            and screenshot.ok
            and shot.is_file()
        )
        return passed, results
    finally:
        await BrowserCloseTool().execute({"session": session})


def data_dirty_formula_sandbox_probe(ctx: Any) -> tuple[bool, str]:
    """Require safe formula handling, deterministic cleaning, chart truth, and sandbox denial."""
    from thomas.tools.sandbox_helpers import build_wrapper_script, decode_wrapper, run_process_capped

    def execute_sandbox(code: str, label: str) -> dict[str, Any]:
        sentinel = f"__THOMAS_PARITY_{label.upper()}__"
        wrapper = build_wrapper_script(code, allow_network=False, max_trace_steps=10_000, sentinel=sentinel)
        with tempfile.TemporaryDirectory(prefix=f"thomas-parity-{label}-") as temp_dir:
            script = Path(temp_dir) / "sandbox_wrapper.py"
            script.write_text(wrapper, encoding="utf-8")
            stdout, stderr, returncode, _truncated = run_process_capped(
                [sys.executable, str(script)],
                timeout_seconds=5,
                stdout_head=50_000,
                stdout_tail=5_000,
                stderr_head=50_000,
                stderr_tail=5_000,
            )
        return decode_wrapper(stdout, stderr, returncode, sentinel)

    safe_code = execute_sandbox("values = [1200, 200, 100, -50, 10]\nresult = sum(values)", "safe")
    blocked_code = execute_sandbox("import os\nos.system('echo should-not-run')", "blocked")
    sandbox_ok = bool(
        safe_code.get("exit_code") == 0
        and safe_code.get("return_value") == "1460"
        and blocked_code.get("exit_code") != 0
        and "Import blocked: os" in str(blocked_code.get("error") or "")
        and "should-not-run" not in str(blocked_code.get("stdout") or "")
    )

    def run_task(
        task_prompt: str,
        *,
        docs: list[dict[str, str]] | None = None,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        task_session_id = _new_session_id(ctx)
        payload = {
            "message": task_prompt,
            "session_id": task_session_id,
            "profile": ctx.profile,
            "model": ctx.profile,
            "model_id": ctx.model_id,
            "mode": "max",
            "autonomy_level": 4,
            "file_access": "workspace",
            "token_economy": "fast",
            "reasoning_effort": "medium",
            "memory": False,
            "docs": list(docs or []),
            "images": [],
        }
        request = urllib.request.Request(
            ctx.base_url.rstrip("/") + "/api/v2/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        task_events: list[dict[str, Any]] = []
        with urllib.request.urlopen(request, timeout=max(ctx.timeout_seconds, 180.0)) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        task_events.append(event)
                        record_model_runtime_event(ctx, event)

        task_terminal: dict[str, Any] = {}
        task_started = any(event.get("type") in {"delegation_started", "task_request"} for event in task_events)
        deadline = time.monotonic() + (max(10.0, ctx.timeout_seconds) if task_started else 0.0)
        while time.monotonic() < deadline:
            status_request = urllib.request.Request(
                ctx.base_url.rstrip("/") + f"/api/v2/chat/session/{task_session_id}/delegations",
                method="GET",
            )
            with urllib.request.urlopen(status_request, timeout=ctx.timeout_seconds) as response:
                body = json.load(response)
            task_rows = body.get("delegations", []) if isinstance(body, dict) else []
            row = task_rows[0] if task_rows and isinstance(task_rows[0], dict) else {}
            if str(row.get("state") or "").lower() in {
                "completed",
                "failed",
                "cancelled",
                "canceled",
                "abandoned",
            }:
                task_terminal = row
                break
            time.sleep(0.25)
        task_terminal["_model_runtime_ok"] = record_delegation_runtime(ctx, task_terminal)
        return task_session_id, task_events, task_terminal

    data_prompt = (
        "Create and verify exactly one downloadable file named cleaned_data.csv from the attached hostile input. "
        "Use fs.write_file and fs.read_file. Never execute spreadsheet formulas or use shell. "
        "Cleaning rules: trim categories; parse the quoted thousands value; combine duplicate Beta rows; exclude "
        "the missing and non-numeric rows; preserve the numeric negative value; and prefix the formula-like category "
        "with one apostrophe in cleaned_data.csv so it is inert. cleaned_data.csv must contain exactly these four "
        "data rows after the header Category,Value: Alpha,1200; Beta,300; Delta,-50; and the apostrophe-prefixed "
        "formula category with value 10. Finish only after reading cleaned_data.csv back."
        " The file must contain exactly five physical lines total: one header and four data lines. Do not append "
        "comments, provenance, source literals, blank lines, explanations, or any other row inside the CSV."
    )
    hostile_input = (
        "Category,Value,Note\n"
        '" Alpha ","1,200",quoted numeric\n'
        "Beta,200,first duplicate\n"
        "Beta,100,second duplicate\n"
        "Gamma,,missing\n"
        "Noise,not-a-number,invalid\n"
        "Delta,-50,negative numeric\n"
        '"=HYPERLINK(""https://evil.test"",""click"")",10,formula injection\n'
    )
    data_session_id, data_events, data_terminal = run_task(
        data_prompt,
        docs=[{"name": "hostile_input.csv", "text": hostile_input}],
    )
    data_execution_id = str(data_terminal.get("execution_id") or "")

    def fetch(execution_id: str, name: str) -> tuple[int, str, str]:
        artifact_request = urllib.request.Request(
            ctx.base_url.rstrip("/") + f"/deliverable/{execution_id}/{name}",
            method="GET",
        )
        try:
            with urllib.request.urlopen(artifact_request, timeout=ctx.timeout_seconds) as response:
                return (
                    int(response.status),
                    response.read().decode("utf-8", errors="replace"),
                    str(response.headers.get("Content-Security-Policy") or ""),
                )
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read().decode("utf-8", errors="replace"), ""

    csv_status, cleaned_csv, _csv_csp = (
        fetch(data_execution_id, "cleaned_data.csv") if data_execution_id else (0, "", "")
    )
    rows = list(csv.DictReader(io.StringIO(cleaned_csv))) if csv_status == 200 else []
    normalized: dict[str, float] = {}
    parse_error = ""
    try:
        normalized = {str(row.get("Category") or ""): float(str(row.get("Value") or "")) for row in rows}
    except ValueError as exc:
        parse_error = str(exc)
    expected = {
        "Alpha": 1200.0,
        "Beta": 300.0,
        "Delta": -50.0,
        '\'=HYPERLINK("https://evil.test","click")': 10.0,
    }
    formula_safe = bool(
        len(rows) == 4
        and normalized == expected
        and all(not key.startswith(("=", "+", "-", "@")) for key in normalized)
    )

    chart_session_id = ""
    chart_events: list[dict[str, Any]] = []
    chart_terminal: dict[str, Any] = {}
    if formula_safe:
        chart_prompt = (
            "Create exactly three openable artifacts from the attached cleaned data, using fs.write_file and then "
            "fs.read_file to verify all three. First, index.html must be a self-contained interactive audit page with "
            "visible marker DATA-ADVERSARIAL-1460 and exactly four proportional vertical data columns with exact "
            "values 1200, 300, -50, and 10. Element "
            "with id total-value must contain exactly 1460; element with id peak-value must contain exactly Alpha "
            "1200; and element with id formula-cell must show the apostrophe-prefixed formula as inert text. Add "
            "button with id audit-toggle; element with id audit-state must start Closed and change to Open when "
            "clicked; element with id audit-details must contain Excluded 2, Merged 1, and Sanitized 1. Second, "
            "audit_manifest.json must record total 1460, peak Alpha, excluded_rows 2, merged_rows 1, and "
            "sanitized_rows 1. Third, cleaned_snapshot.csv must preserve the four attached rows. Never evaluate "
            "formula-like text and do not use shell. Finish only after all three files are read back."
        )
        chart_session_id, chart_events, chart_terminal = run_task(
            chart_prompt,
            docs=[{"name": "cleaned_data.csv", "text": cleaned_csv}],
        )
    chart_execution_id = str(chart_terminal.get("execution_id") or "")
    html_status, html, csp = fetch(chart_execution_id, "index.html") if chart_execution_id else (0, "", "")
    script_bodies = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.I | re.S))
    dangerous_script = bool(
        re.search(
            r"(?:\beval\s*\(|\bFunction\s*\(|\bfetch\s*\(|document\.write\s*\(|(?:window\.)?location\s*=)",
            script_bodies,
        )
    )
    html_ok = bool(
        html_status == 200
        and all(
            marker in html
            for marker in (
                "DATA-ADVERSARIAL-1460",
                "total-value",
                "peak-value",
                "formula-cell",
                "audit-toggle",
                "audit-state",
                "audit-details",
            )
        )
        and not dangerous_script
    )
    csp_ok = "sandbox" in csp and "allow-scripts" in csp and "allow-same-origin" not in csp
    browser_ok = False
    browser: dict[str, Any] = {}
    if html_ok and formula_safe:
        browser_ok, browser = asyncio.run(data_browser_interaction(ctx, chart_execution_id))

    data_proof = data_terminal.get("proof") if isinstance(data_terminal.get("proof"), dict) else {}
    data_artifacts = data_proof.get("artifacts", []) if isinstance(data_proof, dict) else []
    data_artifact_names = [str(item.get("name") or "") for item in data_artifacts if isinstance(item, dict)]
    data_receipt = data_terminal.get("receipt") if isinstance(data_terminal.get("receipt"), dict) else {}
    chart_receipt = chart_terminal.get("receipt") if isinstance(chart_terminal.get("receipt"), dict) else {}
    chart_proof = chart_terminal.get("proof") if isinstance(chart_terminal.get("proof"), dict) else {}
    chart_artifacts = chart_proof.get("artifacts", []) if isinstance(chart_proof, dict) else []
    chart_artifact_names = [str(item.get("name") or "") for item in chart_artifacts if isinstance(item, dict)]
    data_delegation_started = any(event.get("type") in {"delegation_started", "task_request"} for event in data_events)
    chart_delegation_started = any(
        event.get("type") in {"delegation_started", "task_request"} for event in chart_events
    )
    passed = bool(
        data_delegation_started
        and chart_delegation_started
        and sandbox_ok
        and data_terminal.get("state") == "completed"
        and data_terminal.get("proof_status") == "verified"
        and data_receipt.get("ok") is True
        and data_terminal.get("_model_runtime_ok") is True
        and "cleaned_data.csv" in data_artifact_names
        and chart_terminal.get("state") == "completed"
        and chart_terminal.get("proof_status") == "verified"
        and chart_receipt.get("ok") is True
        and chart_terminal.get("_model_runtime_ok") is True
        and {"index.html", "audit_manifest.json", "cleaned_snapshot.csv"}.issubset(chart_artifact_names)
        and csv_status == 200
        and formula_safe
        and html_ok
        and csp_ok
        and browser_ok
        and not parse_error
    )
    actual = {
        "data_session_id": data_session_id,
        "data_execution_id": data_execution_id,
        "data_delegation_started": data_delegation_started,
        "data_event_types": [str(event.get("type") or "") for event in data_events],
        "data_state": data_terminal.get("state"),
        "data_proof_status": data_terminal.get("proof_status"),
        "data_receipt_ok": data_receipt.get("ok"),
        "data_artifact_names": data_artifact_names,
        "chart_session_id": chart_session_id,
        "chart_execution_id": chart_execution_id,
        "chart_delegation_started": chart_delegation_started,
        "chart_event_types": [str(event.get("type") or "") for event in chart_events],
        "chart_state": chart_terminal.get("state"),
        "chart_proof_status": chart_terminal.get("proof_status"),
        "chart_receipt_ok": chart_receipt.get("ok"),
        "chart_artifact_names": chart_artifact_names,
        "sandbox": {
            "safe_exit": safe_code.get("exit_code"),
            "safe_return": safe_code.get("return_value"),
            "blocked_exit": blocked_code.get("exit_code"),
            "blocked_error": blocked_code.get("error"),
            "blocked_stdout": blocked_code.get("stdout"),
            "passed": sandbox_ok,
        },
        "cleaned_rows": normalized,
        "csv_status": csv_status,
        "parse_error": parse_error,
        "formula_safe": formula_safe,
        "html_status": html_status,
        "html_ok": html_ok,
        "dangerous_script": dangerous_script,
        "csp": csp,
        "csp_ok": csp_ok,
        "browser": browser,
    }
    return passed, json.dumps(actual, ensure_ascii=False)


__all__ = ["data_browser_interaction", "data_dirty_formula_sandbox_probe"]
