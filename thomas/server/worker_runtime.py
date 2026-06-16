"""Provider-agnostic background worker.

This is the engine that replaced the legacy ``CodexBridge`` worker fork.  The
old worker hardwired the background task to Codex's *own* native sandbox tools,
throwing away Thomas's tool schemas — so it only worked for one provider.

``run_agent_worker_events`` instead drives the **standard ``AgentLoop`` with the
full Thomas ``ToolRegistry``** — the same engine the CLI and chat already use —
so the worker inherits provider-agnosticism for free.  ``anthropic``,
``openai_codex`` (gpt-5.5 over OAuth), and local ``ollama`` models all run
through this *one* code path; the provider is selected entirely by config.

The split is symmetric with the chatbot-only law:
  * chat surface = ``AgentLoop`` with an empty tool registry -> talks only.
  * worker       = the *same* ``AgentLoop`` with the FULL registry -> does the
    work, in an isolated per-task workspace.

It yields the same bridge-style event dicts the old ``bridge.chat()`` emitted
(``{"type": "text"|"tool_start"|"tool_output"|"done"|"error", ...}``) so the
delegation layer's task-runtime + emitter glue is reused verbatim — only the
event *producer* changed.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig
from thomas.core.events import EventType
from thomas.core.llm_client import LLMClient
from thomas.core.token_economy import compute_max_passes, effective_effort
from thomas.models.worker_overrides import resolve_override
from thomas.server.app_keys import APP_CONFIG, APP_MEMORY, APP_SECRETS

log = logging.getLogger(__name__)


def _embed_secrets(model_cfg: Any, profile: str, secret_store: Any) -> Any:
    """Return a copy of ``model_cfg`` with its API key / OAuth token embedded.

    Provider-blind: a plain ``api_key_secret_name`` lookup for every provider,
    plus the ChatGPT (``openai_codex``) OAuth token path.  Mirrors the server's
    ``_model_cfg_with_secrets`` but takes ``secret_store`` explicitly instead of
    closing over a module-level ``app`` (so it is importable from anywhere).
    """
    if model_cfg is None:
        return None
    cfg_copy = dataclasses.replace(model_cfg)
    if secret_store is None:
        return cfg_copy
    secret_name = str(getattr(cfg_copy, "api_key_secret_name", "") or "").strip()
    if secret_name:
        api_key = secret_store.get(secret_name)
        if api_key:
            cfg_copy.api_key = api_key
    provider = str(getattr(cfg_copy, "provider", "") or "").strip().lower().replace("-", "_")
    if provider == "openai_codex":
        try:
            from thomas.server.openai_codex_oauth import access_token_from_store, has_openai_codex_token

            name = str(profile or getattr(cfg_copy, "name", "") or "chatgpt")
            access_token = access_token_from_store(secret_store, name)
            if access_token:
                cfg_copy.api_key = access_token
            cfg_copy._openai_codex_token_ready = bool(access_token or has_openai_codex_token(secret_store, name))
        except Exception as exc:  # pragma: no cover - defensive token resolution
            log.debug("worker: failed to resolve openai_codex token for %s: %s", profile, exc)
    return cfg_copy


def _resolve_profile(cfg: AppConfig, profile: str | None, role: str | None = None) -> str:
    """Pick the model profile the worker should run, provider-blind.

    Precedence (Calvin's design: chat is separate from the pipeline):
      1. Per-specialist (role) override — the top model selector's per-agent
         choice (e.g. "researcher -> Grok") wins over everything.
      2. The chat's selected model — the pipeline default when no role override.
      3. Global user preference / project default / any configured model.
    """
    db_path = None
    try:
        from thomas.preferences.store import get_db_path

        db_path = get_db_path()
    except Exception:  # pragma: no cover - prefs store unavailable
        db_path = None

    # 1. Per-specialist (role) override.
    if role:
        try:
            from thomas.core.model_resolution import resolve_model_profile_name
            from thomas.server.model_preferences import read_user_model_role_preferences

            role_profile, _role_model_id = read_user_model_role_preferences(
                user_id="default", role=role, db_path=db_path
            )
            role_profile = resolve_model_profile_name(cfg, role_profile)
            if role_profile:
                return role_profile
        except Exception as exc:  # pragma: no cover - falls through to chat default
            log.debug("worker: role model pref lookup failed for role=%s: %s", role, exc)

    # 2. The chat's selected model is the pipeline default.
    if profile and profile in cfg.models:
        return profile

    # 3. Global user preference / project default.
    try:
        from os import environ

        from thomas.core.model_resolution import resolve_effective_model

        resolved_profile, _model_id = resolve_effective_model(
            cfg,
            env_profile=str(environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
            user_id="default",
            db_path=db_path,
        )
        if resolved_profile in cfg.models:
            return resolved_profile
    except Exception as exc:  # pragma: no cover - falls back to default_model
        log.debug("worker: resolve_effective_model failed: %s", exc)
    fallback = str(cfg.default_model or "").strip()
    if fallback not in cfg.models and cfg.models:
        fallback = next(iter(cfg.models))
    return fallback


def _apply_tool_deny(tools: Any, deny: frozenset[str]) -> None:
    """Drop denied tools from the registry, matching by name, dotted-prefix, or category."""
    if not deny:
        return
    registered = getattr(tools, "_tools", None)
    if not isinstance(registered, dict):
        return
    for name, tool in list(registered.items()):
        category = str(getattr(tool, "category", "") or "")
        if any(name == tok or name.startswith(f"{tok}.") or category == tok for tok in deny):
            try:
                tools.unregister(name)
            except Exception:  # pragma: no cover - best-effort pruning
                pass


async def run_agent_worker_events(
    app: Any,
    *,
    prompt: str,
    instructions: str,
    work_dir: Path | str,
    profile: str | None = None,
    role: str | None = None,
    effort: str = "diligent",
    session_id: str | None = None,
    execution_id: str | None = None,
    autonomy_level: int = 4,
) -> AsyncIterator[dict[str, Any]]:
    """Run the standard ``AgentLoop`` (full tools, workspace-confined) and yield
    bridge-style event dicts.

    The tool registry is confined to ``work_dir`` via ``sandbox_root`` — bound at
    tool *registration*, which is per-registry, NOT process-global — so deliverables
    land in the workspace and escapes are blocked WITHOUT an ``os.chdir`` (which is
    process-global and would race across concurrent workers).
    """
    cfg: AppConfig = app[APP_CONFIG]
    secret_store = app.get(APP_SECRETS)
    memory = app.get(APP_MEMORY)

    resolved_profile = _resolve_profile(cfg, profile, role)
    base_model_cfg = cfg.models.get(resolved_profile) or cfg.get_model(resolved_profile)
    model_cfg = _embed_secrets(base_model_cfg, resolved_profile, secret_store)

    override = resolve_override(getattr(model_cfg, "provider", ""), getattr(model_cfg, "model", ""))
    if override.reasoning_effort and hasattr(model_cfg, "reasoning_effort"):
        # Set in place rather than dataclasses.replace(): model_cfg is already a
        # fresh copy from _embed_secrets, and replace() would silently drop the
        # dynamically-attached _openai_codex_token_ready attribute.
        try:
            model_cfg.reasoning_effort = override.reasoning_effort
        except Exception:  # pragma: no cover - field present but not settable
            pass

    # Failover chain, with secrets embedded the same way (provider-blind).
    fallbacks = [
        _embed_secrets(fc, str(getattr(fc, "name", "") or resolved_profile), secret_store)
        for fc in cfg.failover_chain(resolved_profile)
    ]

    # FULL tool surface confined to the per-task workspace (see docstring).
    run_cfg = dataclasses.replace(
        cfg,
        tools=dataclasses.replace(cfg.tools, sandbox_root=str(work_dir), allow_shell=True),
    )
    from thomas.server.app_helpers import _build_tools  # lazy: avoid any app-bootstrap import cycle

    tools = _build_tools(run_cfg)
    _apply_tool_deny(tools, override.tool_deny)

    system_prompt = f"{instructions}{override.prompt_suffix or ''}"

    llm = LLMClient(
        model_cfg,
        fallback_configs=fallbacks,
        failover_enabled=bool(cfg.failover.enabled) and bool(fallbacks),
        failover_cooldown_s=cfg.failover.cooldown_seconds,
        failover_on_auth_error=cfg.failover.fallback_on_auth_error,
        request_overrides=dict(override.request_overrides or {}),
    )

    run_id = str(execution_id or f"worker:{uuid.uuid4().hex}")
    agent = AgentLoop(
        run_cfg,
        llm,
        tools,
        system_prompt=system_prompt,
        memory=memory,
        thread_id=run_id,
        run_id=run_id,
        session_id=str(session_id or run_id),
        # Level 4 = full autonomy / no_human_mode: the worker runs unattended and
        # must not block waiting for tool approvals.
        autonomy_level=autonomy_level,
    )

    # Effort x Autonomy drives the pass budget; a per-model override can still cap it.
    applied_effort = effective_effort(effort, autonomy_level)
    effort_passes = compute_max_passes(applied_effort, run_cfg.max_agent_iterations)
    max_iters = effort_passes if override.max_iterations is None else min(effort_passes, override.max_iterations)

    streamed_text = False
    try:
        async for event in agent.run(
            prompt,
            mode="auto",
            tools_policy="auto",
            token_economy=applied_effort,
            max_iterations=max_iters,
        ):
            etype = event.type
            if etype == EventType.TEXT_DELTA:
                text = str(event.data.get("text") or "")
                if text:
                    streamed_text = True
                    yield {"type": "text", "text": text}
            elif etype == EventType.TOOL_CALL_START:
                name = str(event.data.get("tool_name") or event.data.get("name") or "tool")
                yield {"type": "tool_start", "name": name}
            elif etype == EventType.TOOL_RESULT:
                name = str(event.data.get("tool_name") or "tool")
                yield {"type": "tool_output", "name": name}
            elif etype == EventType.AGENT_ERROR:
                yield {"type": "error", "error": str(event.data.get("error") or "worker failed")}
                return
            elif etype == EventType.AGENT_END:
                # Abnormal terminal state (user interruption, or a denied /
                # suspicious prompt) — the loop did NOT complete the task and does
                # NOT set state.error, so without this it would masquerade as a
                # successful "done". Report failure: failing honestly beats
                # succeeding falsely.
                reason = str(
                    event.data.get("message") or event.data.get("reason") or "worker ended before completing the task"
                )
                yield {"type": "error", "error": reason}
                return
            elif etype == EventType.AGENT_DONE:
                final = str(event.data.get("text") or "").strip()
                # Some providers only deliver the answer in AGENT_DONE (no deltas).
                # Surface it as a text chunk so the result summary is real.
                if final and not streamed_text:
                    yield {"type": "text", "text": final}
                yield {"type": "done"}
                return
            else:
                # Lifecycle/diagnostic events (AGENT_START, AGENT_ITERATION,
                # THINKING, SECURITY_FLAG, TOOL_CALL_*_DELTA, STATUS, ...) have no
                # consumer-facing payload here; log for debugging and continue.
                log.debug("worker: ignoring unmapped agent event %s", getattr(etype, "name", etype))
        # Loop ended without any terminal event (AGENT_DONE/ERROR/END). A few
        # early-return paths inside the loop can do this; warn so it is debuggable,
        # then finish as done so the task still terminates rather than hanging.
        log.warning("worker: agent event stream ended without a terminal event; finishing as done")
        yield {"type": "done"}
    finally:
        # Background workers are long-lived and many: a leaked httpx client per
        # task is a real resource bug. Do NOT close the shared app memory engine.
        await llm.close()
