"""OpenAI-compatible chat batch mode for the legacy /api/chat route."""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import time
from typing import Any

from aiohttp import web

from thomas.models.batching import (
    OpenAICompatBatchClient,
    build_completion_request,
    extract_batch_results,
    extract_result_error,
    extract_result_text,
    parse_batch_state,
)
from thomas.models.capabilities import supports


async def maybe_execute_batch_chat(
    *,
    request: web.Request,
    sid: str,
    session: Any,
    mode: str,
    model_cfg: Any,
    prompt_text: str,
    token_economy_meta: dict[str, Any],
    apply_usage_budget: Any,
    start_t: float,
    task_ledger_update: Any = None,
) -> web.StreamResponse | None:
    """Execute a batched chat request via the OpenAI-compatible batch API.

    When ``task_ledger_update`` is provided (the chat deps closure), the batch
    flow records the same lifecycle transitions as the regular agent loop
    (chat.request → chat.route → chat.done). Without those updates, the
    per-session task ledger stays stuck at ``in_progress`` even after the
    batch returns a final ``done`` event — caught by
    ``tests/test_server_task_ledger.py::test_task_ledger_updates_for_batch_mode_completion``.
    """
    if str(mode or "").strip().lower() != "batch":
        return None
    if str(getattr(model_cfg, "provider", "") or "").strip().lower() != "openai_compat":
        return None
    if not supports(model_cfg, "batch"):
        return None

    user_text = str(prompt_text or "")
    if not isinstance(getattr(session, "conversation", None), list):
        session.conversation = []
    session.conversation.append({"role": "user", "content": user_text})

    def _ledger(*, status: str, last_progress: str, source: str) -> None:
        if not callable(task_ledger_update):
            return
        with contextlib.suppress(Exception):
            task_ledger_update(
                sid,
                status=status,
                missing_inputs=[],
                last_progress=last_progress,
                source=source,
                force_event=True,
            )

    _ledger(
        status="in_progress",
        last_progress="Batch mode: queuing provider batch request.",
        source="chat.request",
    )

    run_id = secrets.token_urlsafe(10)
    seq = 0

    def _next_seq() -> int:
        nonlocal seq
        value = int(seq)
        seq += 1
        return value

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "application/x-ndjson; charset=utf-8",
            "Cache-Control": "no-cache",
        },
    )
    await response.prepare(request)

    async def send(obj: dict[str, Any]) -> None:
        payload = dict(obj)
        payload.setdefault("run_id", run_id)
        payload.setdefault("seq", _next_seq())
        line = json.dumps(payload, ensure_ascii=False)
        with contextlib.suppress(ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            await response.write(line.encode("utf-8") + b"\n")

    client: Any = None
    try:
        try:
            from thomas.server import app as server_app

            client_cls = getattr(server_app, "OpenAICompatBatchClient", OpenAICompatBatchClient)
        except Exception:
            client_cls = OpenAICompatBatchClient

        client = client_cls(model_cfg)
        await send(
            {
                "type": "route",
                "route": {"path": "batch", "confidence": 1.0},
                "mode": "batch",
                "tools_policy": "never",
                "token_economy": token_economy_meta,
                "autonomy_level": 3,
                "autonomy_name": "Standard",
            }
        )
        _ledger(
            status="in_progress",
            last_progress="Batch mode: provider client created.",
            source="chat.route",
        )
        await send({"type": "thinking", "text": "Submitting provider batch request..."})

        completion_request = build_completion_request(
            model_cfg=model_cfg,
            messages=[{"role": "user", "content": user_text}],
        )
        submission = await client.create_and_add_chat_requests(
            batch_name=f"thomas-chat-{sid[:12]}",
            requests=[
                {
                    "batch_request_id": f"{sid}-batch-1",
                    "request": completion_request,
                }
            ],
        )

        deadline = time.monotonic() + max(0.2, min(float(getattr(model_cfg, "timeout_s", 30.0) or 30.0), 2.0))
        while time.monotonic() < deadline:
            batch_payload = await client.get_batch(batch_id=submission.batch_id)
            batch_state = parse_batch_state(batch_payload)
            if batch_state.get("done"):
                break
            await asyncio.sleep(0.03)
        else:
            await send({"type": "error", "error": "Batch mode timed out waiting for provider results."})
            return response

        results_payload = await client.list_batch_results(batch_id=submission.batch_id)
        results = extract_batch_results(results_payload)
        if not results:
            await send({"type": "error", "error": "Batch mode returned no results."})
            return response

        result = results[0]
        result_error = extract_result_error(result)
        if result_error:
            await send({"type": "error", "error": result_error})
            return response

        answer = extract_result_text(result)
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        budget_report = await apply_usage_budget(0)
        token_report = {
            "mode": "batch",
            "rules_of_road": {},
            "token_economy": dict(token_economy_meta),
        }
        if isinstance(budget_report, dict):
            token_report["budget"] = budget_report

        if answer:
            session.conversation.append({"role": "assistant", "content": answer})
            await send({"type": "text", "text": answer})
        await send(
            {
                "type": "done",
                "text": answer,
                "iterations": 1,
                "tool_calls": 0,
                "usage": usage,
                "run_usage": usage,
                "session_usage": usage,
                "token_report": token_report,
                "token_economy": token_economy_meta,
                "rules_of_road": token_report.get("rules_of_road", {}),
                "elapsed_ms": float((time.monotonic() - start_t) * 1000.0),
            }
        )
        # Mirror the regular agent loop's terminal ledger update so per-session
        # task ledger queries see "complete" instead of staying stuck at
        # "in_progress" after batch mode finishes.
        _ledger(
            status="complete",
            last_progress=str(answer or "Batch mode finished."),
            source="chat.done",
        )
        return response
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()
        with contextlib.suppress(Exception):
            await response.write_eof()
