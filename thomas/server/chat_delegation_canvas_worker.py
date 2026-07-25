"""Two-stage streaming execution for Canvas generation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable


class _CanvasStall(RuntimeError):
    """A retryable Canvas provider or semantic-review failure."""


class _CanvasCancelled(RuntimeError):
    """The user asked for this Canvas run to stop."""


# How often the wait for the next stream event pauses to notice a cancellation.
# The wait itself can legitimately last minutes, and asyncio.wait_for cannot be
# interrupted, so it is taken in slices instead of one long sleep. Nothing about
# the deadline changes -- the slices are added up against the same budget -- but
# pressing cancel now takes effect within seconds rather than never.
_CANCEL_POLL_S = 3.0


async def _next_event(events: Any, budget_s: float, cancelled: Callable[[], bool]) -> Any:
    """Await the next stream event without becoming deaf to cancellation.

    asyncio.wait_for cannot be interrupted once it is waiting, so a single long
    wait makes the run uncancellable for its whole duration. The same budget is
    spent in short slices instead, checking between them. Raises TimeoutError
    when the budget is exhausted, exactly as the single wait did.
    """
    waited = 0.0
    while True:
        if cancelled():
            raise _CanvasCancelled()
        if waited >= budget_s:
            raise asyncio.TimeoutError()
        slice_s = min(_CANCEL_POLL_S, budget_s - waited)
        try:
            return await asyncio.wait_for(events.__anext__(), timeout=slice_s)
        except asyncio.TimeoutError:
            waited += slice_s


# There is deliberately NO deadline on thinking. A reasoning model can work for
# minutes before it emits a first token, and the transport reports nothing at all
# while it does -- so a time-to-first-token wall cannot tell "still thinking" from
# "hung", and it guesses wrong on exactly the requests worth waiting for. The old
# 75s wall killed real work twice per run and surfaced as "the Canvas failed".
#
# What remains is not a work deadline, it is a dead-socket backstop. A hung
# provider would otherwise hold _CANVAS_LLM_LOCK forever and take every later
# Canvas job down with it, so silence this long is treated as a broken
# connection rather than a slow one.
_DEAD_SOCKET_S = 900.0

# Once tokens are actually flowing, a long gap does mean the stream died.
_MID_STREAM_IDLE_S = 120.0


async def run_canvas_worker(
    *,
    execution_id: str,
    prompt: str,
    root: Path,
    profile: str | None = None,
    model_id: str | None = None,
    emit_progress: Callable[[str], Awaitable[None]] | None = None,
    record_runtime: Callable[[dict[str, Any]], None] | None = None,
    session_llm: Any = None,
    runtime_policy: dict[str, Any] | None = None,
) -> str:
    """Generate, review, and publish a self-contained Canvas document."""

    from thomas.core import task_bot_runtime
    from thomas.server import chat_delegation_canvas as canvas
    from thomas.server.chat_budget_ledger import ChatBudgetError, budget_context, get_chat_budget_ledger
    from thomas.server.chat_budget_scope import scope_from_runtime_policy

    canvas.canvas_start(execution_id, title=str(prompt or "")[:80])
    budget_ctx = budget_context(runtime_policy)
    requires_dedicated_llm = bool(budget_ctx.get("ledger_path"))
    # Canvas runs after the foreground reply has started and can outlive that HTTP
    # turn. A dedicated low-latency client preserves the selected profile/model
    # without concurrently mutating the foreground session client's stream state.
    # Reuse the authenticated session client only when a dedicated client cannot
    # be constructed (for example an injected test or custom provider).
    llm = None
    owns_llm = False
    if runtime_policy and session_llm is not None:
        try:
            llm = type(session_llm)(
                session_llm.config,
                fallback_configs=list(getattr(session_llm, "_fallback_configs", ()) or ()),
                failover_enabled=bool(getattr(session_llm, "_failover_enabled", False)),
                failover_cooldown_s=int(getattr(session_llm, "_failover_cooldown_s", 300)),
                failover_on_auth_error=bool(getattr(session_llm, "_failover_on_auth_error", False)),
                max_retries=int(getattr(session_llm, "_max_retries", 3)),
                base_retry_delay_s=float(getattr(session_llm, "_base_retry_delay", 0.8)),
                request_overrides=dict(getattr(session_llm, "_request_overrides", {}) or {}),
            )
            owns_llm = True
        except (AttributeError, TypeError, ValueError):
            llm = None
    if llm is None:
        llm = canvas.build_canvas_llm(root, profile, model_id)
    if llm is None and not requires_dedicated_llm:
        llm = session_llm
    if llm is None or not hasattr(llm, "stream_chat"):
        canvas.canvas_finish(execution_id, "failed")
        if requires_dedicated_llm:
            raise RuntimeError("No dedicated streaming LLM available for the budgeted canvas worker")
        raise RuntimeError("No streaming LLM available for the canvas worker")
    policy_instructions = str((runtime_policy or {}).get("system_instructions") or "").strip()
    quality_policy = dict((runtime_policy or {}).get("quality") or {})
    review_pass_limit = 2
    if bool(quality_policy.get("enforce")):
        review_pass_limit = max(2, min(3, int(quality_policy.get("max_agent_iterations") or 2)))

    def policy_system(base: str) -> str:
        if not policy_instructions:
            return base
        return f"{base}\n\nUser-approved runtime instructions:\n{policy_instructions}"

    usage_before = 0
    previous_budget_scope = None
    budget_scope = None
    set_budget_scope = None

    async def emit(message: str) -> None:
        if emit_progress is None:
            return
        try:
            await emit_progress(message)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return

    def _cancelled() -> bool:
        """Has the user asked this run to stop?

        Nothing in the Canvas path asked this before, so a cancel set the flag
        and no code ever read it: the run kept going, the record stayed in
        `executing` for as long as the server lived, and the chat could only
        repeat its last status. Observed on a live request for a banana graph --
        seven minutes of "Planning the design", a cancel that did nothing, and
        Thomas explaining that it could not see inside the worker.
        """
        try:
            return bool(task_bot_runtime.is_cancel_requested(execution_id, repo_root=root))
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return False  # never let a bookkeeping error kill a healthy run

    async def stream(
        messages: list[dict[str, Any]],
        *,
        to_canvas: bool,
        label: str,
        on_text: Callable[[str], None] | None = None,
    ) -> str:
        last_error = "stalled"
        attempts_used = 0
        for attempt in range(2):
            attempts_used = attempt + 1
            parts: list[str] = []
            token_count = 0
            got_first = False
            event_count = 0
            try:
                canvas._diag(f"[stream] {label} a{attempt}: opening; client={type(llm).__name__}")
                events = llm.stream_chat(messages=messages, tools=None).__aiter__()
                while True:
                    timeout = _MID_STREAM_IDLE_S if got_first else _DEAD_SOCKET_S
                    try:
                        event = await _next_event(events, timeout, _cancelled)
                    except StopAsyncIteration:
                        canvas._diag(
                            f"[stream] {label} a{attempt}: StopAsyncIteration after "
                            f"{event_count} events, {token_count} tokens"
                        )
                        break
                    except asyncio.TimeoutError as exc:
                        # Say what actually happened. "canvas_failed" in the issue
                        # ledger told nobody whether the model was slow, the socket
                        # was dead, or the request never left -- so every occurrence
                        # cost a fresh investigation.
                        reason = (
                            f"no data at all for {timeout:.0f}s before the first token "
                            f"({event_count} stream events) -- treating the connection as dead"
                            if not got_first
                            else f"stream went silent for {timeout:.0f}s after {token_count} tokens"
                        )
                        raise _CanvasStall(reason) from exc
                    event_count += 1
                    event_type = str(getattr(event, "type", "") or "")
                    data = getattr(event, "data", {}) or {}
                    if event_type == "token":
                        token = str(data.get("text", "") or "")
                        if not token:
                            continue
                        got_first = True
                        parts.append(token)
                        token_count += 1
                        if to_canvas:
                            canvas.canvas_append(execution_id, token)
                        if on_text is not None and token_count % 8 == 0:
                            try:
                                on_text("".join(parts))
                            except (AttributeError, RuntimeError, TypeError, ValueError):
                                pass
                        if token_count % 30 == 0:
                            await emit(label)
                    elif event_type == "error":
                        raise _CanvasStall("provider stream error")
                text = "".join(parts)
                if on_text is not None:
                    try:
                        on_text(text)
                    except (AttributeError, RuntimeError, TypeError, ValueError):
                        pass
                if text.strip():
                    return text
                last_error = "empty output"
            except _CanvasCancelled:
                # Listed before the handlers below because it is a RuntimeError
                # and would otherwise be swallowed as a retryable fault -- the
                # run would be retried instead of stopped, which is the opposite
                # of what was asked.
                raise
            except _CanvasStall as exc:
                last_error = str(exc)
                canvas._diag(f"[stream] {label} a{attempt}: STALL {exc}")
                # A stall with no data whatsoever is a dead connection, not a
                # model thinking. Retrying spends the whole wait again while
                # holding the global canvas lock, so one broken request would
                # block every other conversation's canvas for twice as long --
                # and a socket that produced nothing the first time has no more
                # reason to speak the second. A stall AFTER data arrived is
                # different, and is still worth one retry.
                if not got_first and event_count == 0:
                    canvas._diag(f"[stream] {label}: dead connection, not retrying")
                    break
            except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
                last_error = type(exc).__name__
                canvas._diag(f"[stream] {label} a{attempt}: EXC {last_error}")
            if attempt == 0:
                await asyncio.sleep(1.5)
        raise _CanvasStall(f"{attempts_used} attempt(s): {last_error}")

    await canvas._CANVAS_LLM_LOCK.acquire()
    budget_reconciled = False
    try:
        usage_at_start = getattr(llm, "session_usage", None)
        usage_before = max(
            max(0, int(getattr(usage_at_start, "prompt_tokens", 0) or 0))
            + max(0, int(getattr(usage_at_start, "completion_tokens", 0) or 0)),
            max(0, int(getattr(usage_at_start, "total_tokens", 0) or 0)),
        )
        reset_runtime_trace = getattr(llm, "reset_runtime_trace", None)
        if callable(reset_runtime_trace):
            reset_runtime_trace()
        if budget_ctx.get("ledger_path"):
            budget_ledger = get_chat_budget_ledger(str(budget_ctx["ledger_path"]))
            budget_scope = scope_from_runtime_policy(
                budget_ledger,
                dict(runtime_policy or {}),
                user_id=str(budget_ctx.get("user_id") or "default"),
                session_id=str(budget_ctx.get("session_id") or "default"),
            )
            set_budget_scope = getattr(llm, "set_budget_scope", None)
            if callable(set_budget_scope):
                previous_budget_scope = set_budget_scope(budget_scope)
        if budget_scope is not None:
            await budget_scope.preflight()
        await emit("Planning the design…")
        build_state: dict[str, Any] = {"n": 0, "sw": 720, "sh": 520, "shell": False}

        def on_plan(accumulated: str) -> None:
            stage = canvas._partial_stage(accumulated)
            if stage:
                build_state["sw"], build_state["sh"] = stage["w"], stage["h"]
                if not build_state["shell"]:
                    canvas.canvas_set_shell(execution_id, {**stage, "stagger": 70})
                    build_state["shell"] = True
            if not build_state["shell"]:
                return
            for element in canvas.stream_elements(accumulated, build_state["n"]):
                rendered = canvas._render_element(
                    element,
                    build_state["n"],
                    build_state["sw"],
                    build_state["sh"],
                )
                build_state["n"] += 1
                if rendered is not None:
                    canvas.canvas_add_element(execution_id, rendered[0], rendered[1])

        plan_messages = [
            {"role": "system", "content": policy_system(canvas._PLAN_SYSTEM)},
            {"role": "user", "content": str(prompt or "")},
        ]
        plan = ""
        html = ""
        review = None
        for review_pass in range(review_pass_limit):
            if review_pass:
                canvas.canvas_start(execution_id, title=str(prompt or "")[:80])
                build_state.update({"n": 0, "sw": 720, "sh": 520, "shell": False})
                await emit("Repairing the design after review…")
            plan = await stream(
                plan_messages,
                to_canvas=False,
                label="Building it on the canvas…" if not review_pass else "Repairing the canvas…",
                on_text=on_plan,
            )
            canvas.canvas_set_plan(execution_id, plan)
            await emit("Drawing it on the canvas…")
            html = ""
            try:
                built = canvas.build_canvas_html(plan)
                if built.strip() and canvas._conforms_to_contract(built):
                    html = built
                    canvas._diag(f"[render] deterministic OK, {len(html)} chars")
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                canvas._diag(f"[render] deterministic compile failed: {exc}")
            if not html.strip():
                canvas._diag("[render] falling back to LLM render bot")
                render_user = f"USER REQUEST:\n{str(prompt or '')}\n\nDESIGN PLAN TO RENDER EXACTLY:\n{plan}"
                for _render_pass in range(2):
                    html_text = await stream(
                        [
                            {"role": "system", "content": policy_system(canvas._RENDER_SYSTEM)},
                            {"role": "user", "content": render_user},
                        ],
                        to_canvas=True,
                        label="Drawing it on the canvas…",
                    )
                    html = canvas.extract_html(html_text)
                    if html.strip() and canvas._conforms_to_contract(html):
                        break
                    render_user += (
                        "\n\nIMPORTANT: your previous attempt did NOT follow the render contract. The "
                        'document MUST contain <div id="tc-stage" data-reveal="pending"> wrapping the visual, '
                        'every animatable element must carry style="--i:N", and a final script must flip '
                        'data-reveal to "play" after document.fonts.ready + a double requestAnimationFrame, '
                        "with a setTimeout(...,2500) safety net. Redo it following the contract exactly."
                    )
            if not html.strip():
                raise _CanvasStall("render produced empty HTML")
            review = canvas.review_canvas_html(str(prompt or ""), html)
            if review.passed:
                break
            plan_messages = [
                {"role": "system", "content": policy_system(canvas._PLAN_SYSTEM)},
                {
                    "role": "user",
                    "content": (
                        f"USER REQUEST:\n{str(prompt or '')}\n\nFAILED DESIGN PLAN:\n{plan}\n\n"
                        "REVIEW FINDINGS:\n- "
                        + "\n- ".join(issue.message for issue in review.issues)
                        + "\n\nReturn a corrected plan. Preserve every requested label and value as stable, "
                        "visible text, keep each chart label adjacent to its value, and match the requested subject."
                    ),
                },
            ]
        assert review is not None
        canvas.canvas_set_review(execution_id, review.to_dict())
        if not review.passed:
            raise _CanvasStall(
                "canvas review failed after repair: " + "; ".join(issue.message for issue in review.issues)
            )
        if budget_scope is not None:
            usage = getattr(llm, "session_usage", None)
            usage_after = max(
                max(0, int(getattr(usage, "prompt_tokens", 0) or 0))
                + max(0, int(getattr(usage, "completion_tokens", 0) or 0)),
                max(0, int(getattr(usage, "total_tokens", 0) or 0)),
            )
            budget_reconciled = True
            await budget_scope.reconcile_unscoped_usage(max(0, usage_after - usage_before))
        canvas.canvas_set_html(execution_id, html)
        if record_runtime is not None:
            from thomas.server.model_runtime_receipt import model_runtime_receipt

            record_runtime(
                model_runtime_receipt(
                    llm,
                    requested_profile=str(profile or ""),
                    requested_model_id=str(model_id or ""),
                )
            )
        canvas.canvas_finish(execution_id, "done")
        return html
    except _CanvasStall as exc:
        current = canvas.canvas_get(execution_id) or {}
        if str(current.get("review_status") or "pending") == "pending":
            canvas.canvas_set_review(
                execution_id,
                {"status": "failed", "issues": [{"code": "generation_failed", "message": str(exc), "details": {}}]},
            )
        canvas.canvas_finish(execution_id, "failed")
        raise RuntimeError(f"canvas generation failed: {exc}") from exc
    except ChatBudgetError as exc:
        canvas.canvas_finish(execution_id, "failed")
        raise RuntimeError(f"canvas token budget failed: {exc}") from exc
    finally:
        reconciliation_error = None
        if budget_scope is not None and not budget_reconciled:
            usage = getattr(llm, "session_usage", None)
            usage_after = max(
                max(0, int(getattr(usage, "prompt_tokens", 0) or 0))
                + max(0, int(getattr(usage, "completion_tokens", 0) or 0)),
                max(0, int(getattr(usage, "total_tokens", 0) or 0)),
            )
            try:
                await budget_scope.reconcile_unscoped_usage(max(0, usage_after - usage_before))
            except ChatBudgetError as exc:
                reconciliation_error = exc
        if callable(set_budget_scope):
            set_budget_scope(previous_budget_scope)
        if owns_llm:
            close = getattr(llm, "close", None)
            if callable(close):
                try:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
                except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                    canvas._diag(f"[stream] owned client close failed: {type(exc).__name__}")
        canvas._CANVAS_LLM_LOCK.release()
        if reconciliation_error is not None:
            raise reconciliation_error
