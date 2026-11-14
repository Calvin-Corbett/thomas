"""One Build pass per coding agent, behind one signature.

Each :class:`~thomas.core.coding_agents.CodingAgentSpec` names its pass here as
``module:function``; every pass takes an
:class:`~thomas.core.coding_agents.AgentRunRequest` and returns the
``CliDispatchResult`` the runner already reports. The runner looks the name up
(:func:`pass_for`), so a new agent's pass needs no runner edit;
``thomas/core/coding_agents/builtins.py`` says what else a new agent needs.

What a pass may NOT decide is already in the request: whether it gets a shell
(``allow_shell``, answered by ``direct_shell_allowed`` for this exact policy —
in the cage that shell runs as the cage account), the file-access fence, and the
event sink its translated output goes to.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from typing import Any

from thomas.core.coding_agents import (
    ANTHROPIC_KEY_MISSING_MSG,
    THOMAS_FORGE_PROFILE,
    AgentRunRequest,
    CodingAgentSpec,
    model_family,
)

from .dispatch_agent_loop import CHATGPT_NOT_CONNECTED_MSG, dispatch_via_agent_loop
from .dispatch_claude_cli import SAFE_CLI_TOOLS, dispatch_via_claude_cli

#: The profile field ``ForgeCodeSettings.child_environment`` fills with the
#: Anthropic key when Thomas's own loop runs a Claude model.
_FORGE_KEY_ENV = "THOMAS_MODELS_FORGECODE_API_KEY"


def pass_for(spec: CodingAgentSpec) -> Callable[[AgentRunRequest], Any]:
    """The pass function a spec's ``dispatch`` names — an ordinary import."""
    module_name, _, attr = str(spec.dispatch).partition(":")
    if not module_name or not attr:
        raise ValueError(f"{spec.label} names no pass ({spec.dispatch!r})")
    return getattr(importlib.import_module(module_name), attr)


def _hooks(request: AgentRunRequest) -> dict[str, Any]:
    """The injection hooks a request actually set, and only those.

    The runner never set them before the picker, so a caller that wraps a pass
    and supplies its own ``runner``/``verify`` keeps working instead of meeting
    a duplicate keyword.
    """
    hooks: dict[str, Any] = {
        key: value
        for key, value in (("runner", request.runner), ("emit", request.emit), ("verifier", request.verifier))
        if value is not None
    }
    if not request.verify:
        hooks["verify"] = False
    return hooks


def run_thomas_pass(request: AgentRunRequest) -> Any:
    """Thomas's own AgentLoop: GPT through ChatGPT, Claude through an Anthropic key.

    Claude never borrows the ChatGPT token: it runs on the isolated ``forgecode``
    profile the parent pinned to ``anthropic``. The key is the one-run credential
    on the start pipe (``prepare_code_oauth_credential`` sends your Anthropic key
    for this arm, including one saved in the app), or one already in the
    environment; with neither it is refused with the sentence that names both
    ways out.
    """
    plan = request.plan
    claude = model_family(plan.model) == "claude"
    token = request.oauth_access_token
    if claude:

        def connected() -> bool:
            return bool(token) or bool(str(os.environ.get(_FORGE_KEY_ENV) or "").strip())

    else:

        def connected() -> bool:
            return bool(token)

    return dispatch_via_agent_loop(
        request.goal,
        cwd=request.cwd,
        definition=request.definition,
        plan=request.task_plan,
        profile=THOMAS_FORGE_PROFILE if claude else (plan.profile or "openai_codex"),
        timeout=request.timeout,
        dry_run=request.dry_run,
        max_fix_iters=request.max_fix_iters,
        history=request.history,
        token_check=connected,
        allow_shell=request.allow_shell,
        file_access=request.file_access,
        guardrails=request.guardrails,
        autonomy_level=request.autonomy_level,
        protected_paths=list(request.protected_paths) or None,
        token_economy=request.token_economy,
        oauth_access_token=token,
        allow_without_history=request.allow_without_history,
        not_connected_msg=ANTHROPIC_KEY_MISSING_MSG if claude else CHATGPT_NOT_CONNECTED_MSG,
        **_hooks(request),
    )


def run_claude_code_pass(request: AgentRunRequest) -> Any:
    """Claude Code headless, on Thomas's tool list; Bash only where the policy allows a shell."""
    return dispatch_via_claude_cli(
        request.goal,
        cwd=request.cwd,
        definition=request.definition,
        plan=request.task_plan,
        model=request.plan.model,
        timeout=request.timeout,
        dry_run=request.dry_run,
        allowed_tools=SAFE_CLI_TOOLS + (("Bash",) if request.allow_shell else ()),
        max_fix_iters=request.max_fix_iters,
        history=request.history,
        file_access=request.file_access,
        guardrails=request.guardrails,
        autonomy_level=request.autonomy_level,
        protected_paths=list(request.protected_paths) or None,
        allow_without_history=request.allow_without_history,
        **_hooks(request),
    )
