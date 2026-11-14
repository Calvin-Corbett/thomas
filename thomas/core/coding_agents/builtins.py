"""The agents Thomas ships with: its own loop, and Claude Code.

Adding an agent is a :class:`~thomas.core.coding_agents.spec.CodingAgentSpec`
listed in :data:`BUILTIN_AGENTS`, plus a ``(request: AgentRunRequest) ->
CliDispatchResult`` function where its ``dispatch`` names. The picker and the
runner's ``--agent`` choices read the registry, so they need no edit; the launch
journal records the agent as plain text, and ``praxis.launch`` still branches on
``"thomas"`` for which profile its helpers use. ``forge_code_settings`` does: it asks "is this Thomas?" for what
the child environment pins and how the model is recorded, and
``prepare_code_oauth_credential`` asks it for which credential rides the start
pipe. And GPT and Claude are the only families Build knows (``families.py``):
any other model is refused before dispatch and the runner's ``--family`` takes
only those two, so an agent for a third family (Gemini CLI on Gemini models)
needs that taught first.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from thomas.core import claude_plan
from thomas.core.coding_agents.spec import AgentAvailability, AgentLaunchPlan, CodingAgentSpec

#: The profile the in-process loop uses for GPT: an OAuth alias of your ChatGPT
#: connection, never the paid OPENAI_API_KEY.
THOMAS_GPT_PROFILE = "openai_codex"
#: The isolated profile ``ForgeCodeSettings.child_environment`` pins per run. The
#: Anthropic arm sets the same one, which is how Thomas's loop reaches Claude
#: through a key rather than through anybody's personal subscription.
THOMAS_FORGE_PROFILE = "forgecode"

#: Where Thomas's own loop finds an Anthropic key. A product that drives Claude
#: Code on a personal Claude subscription can be restricted; a key cannot, so the
#: default agent has a path to Claude that does not depend on one.
ANTHROPIC_KEY_ENV = ("ANTHROPIC_API_KEY", "THOMAS_ANTHROPIC_API_KEY")

#: The refusal when Thomas's own loop is asked for a Claude model with no key. It
#: names the two ways out, and names the OTHER agent as one of them — a picker
#: whose refusals do not mention the thing that would work is a dead end. The key
#: places it names are the ones :func:`anthropic_api_key` reads.
ANTHROPIC_KEY_MISSING_MSG = (
    "Thomas's own loop runs Claude through Anthropic's API, and there is no Anthropic key on this machine — "
    "paste one into the anthropic model's key box in the model menu, or into Settings > Anthropic Configuration, "
    "or pick the Claude Code agent, which carries its own sign-in."
)

#: Anthropic's API root in the form Thomas's transport needs: it appends only
#: ``/messages`` (``thomas/core/llm_streaming_anthropic.py``), so ``/v1`` is part of it.
ANTHROPIC_API_ROOT = "https://api.anthropic.com/v1"

# Where keys saved in the app live. The server sets this (its SecretStore and
# preferences are out of ``core``'s reach); a process with no server, like the
# Build runner, has only the environment and gets its key on the start pipe.
_stored_key_reader: Callable[[], str] | None = None


def read_stored_anthropic_key_with(reader: Callable[[], str] | None) -> None:
    """Let :func:`anthropic_api_key` see a key saved in the app, not only one in the environment."""
    global _stored_key_reader
    _stored_key_reader = reader


def stored_anthropic_key() -> str:
    """The Anthropic key saved in the app, or "" where nothing can read one."""
    if _stored_key_reader is None:
        return ""
    try:
        return str(_stored_key_reader() or "").strip()
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return ""


def anthropic_api_key() -> str:
    """The Anthropic key this machine has for Thomas's own loop, or "".

    The environment first, then the key saved in the app. Settings and the model
    menu save keys in the app, so reading only ``os.environ`` meant the place the
    refusal sent you could not fix it.
    """
    for name in ANTHROPIC_KEY_ENV:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return stored_anthropic_key()


def anthropic_api_root(sdk_base_url: str | None = "") -> str:
    """Thomas's form of an ``ANTHROPIC_BASE_URL``.

    That variable belongs to Anthropic's SDK, which appends ``/v1/messages`` to it,
    so its usual value — ``https://api.anthropic.com``, which Claude Code sessions
    set — names the host, not the API root. Copied as it was, Thomas's transport
    posted to ``https://api.anthropic.com/messages`` and Anthropic answered 404.
    """
    text = str(sdk_base_url or "").strip().rstrip("/")
    if not text:
        return ANTHROPIC_API_ROOT
    return text if text.endswith("/v1") else f"{text}/v1"


#: What the picker says about Thomas's own loop when no Anthropic key is found.
THOMAS_ROUTES_DETAIL = (
    "Thomas's own agent loop. GPT models run through your ChatGPT connection; "
    "Claude models run through an Anthropic API key."
)


def _thomas_availability() -> AgentAvailability:
    """Thomas's loop is always installed — it *is* Thomas.

    Installed and signed in unconditionally, and that is not optimism: this probe
    also runs inside the Build runner subprocess, where the server's secret store
    is out of reach. Reporting the default agent as missing there would be a false
    absence. Per-family reach is a different question. For Claude, it is answered
    from your Anthropic key, including one saved in the app (the server sets
    :func:`read_stored_anthropic_key_with`). For GPT it answers yes and the
    dispatcher checks your ChatGPT connection at launch, refusing with
    ``CHATGPT_NOT_CONNECTED_MSG`` if it is missing.
    """
    key = anthropic_api_key()
    detail = THOMAS_ROUTES_DETAIL
    if key:
        detail = "Thomas's own agent loop. GPT runs through your ChatGPT connection, Claude through your Anthropic key."
    return AgentAvailability(installed=True, signed_in=True, detail=detail)


def _thomas_reaches(family: str) -> bool:
    """GPT is gated at dispatch (the ChatGPT token arrives on the start pipe);
    Claude needs an Anthropic key, in the environment or saved in the app."""
    return family != "claude" or bool(anthropic_api_key())


def _thomas_plan(model: str) -> AgentLaunchPlan:
    """GPT rides the ChatGPT OAuth profile; Claude rides the Anthropic API key."""
    from thomas.core.coding_agents.families import is_gpt_model

    if is_gpt_model(model):
        return AgentLaunchPlan(
            agent_id="thomas",
            model=model,
            profile=THOMAS_FORGE_PROFILE if str(model or "").lower().startswith("gpt-") else THOMAS_GPT_PROFILE,
            provider="openai_codex",
        )
    return AgentLaunchPlan(
        agent_id="thomas",
        model=model,
        profile=THOMAS_FORGE_PROFILE,
        provider=claude_plan.CLAUDE_PLAN_PROVIDER,
    )


def _claude_code_availability() -> AgentAvailability:
    """Installed = the ``claude`` CLI is on PATH. Signed in = it has not refused for want of a login.

    ``profiles_without_a_signin`` is what the CLI itself told Thomas the last time
    it refused, and it is forgotten again the moment that profile answers, so
    signing in needs no restart.
    """
    path = claude_plan.claude_cli_path()
    if not path:
        return AgentAvailability(installed=False, signed_in=False, detail=claude_plan.CLAUDE_CLI_MISSING_GUIDANCE)
    refused = "claude_cli" in claude_plan.profiles_without_a_signin()
    if refused:
        return AgentAvailability(installed=True, signed_in=False, detail=claude_plan.CLAUDE_CLI_LOGIN_GUIDANCE)
    return AgentAvailability(
        installed=True,
        signed_in=True,
        detail=f"Claude Code found at {path}; it carries its own sign-in.",
    )


def _claude_code_plan(model: str) -> AgentLaunchPlan:
    """Claude Code brings its own sign-in, so there is no Thomas profile to name."""
    return AgentLaunchPlan(agent_id="claude_code", model=model or "sonnet", profile="", provider="")


THOMAS_AGENT = CodingAgentSpec(
    id="thomas",
    label="Thomas",
    summary="Thomas's own agent loop, in process — the default.",
    dispatch="thomas.forge.anvil.agent_passes:run_thomas_pass",
    model_families=("gpt", "claude"),
    availability=_thomas_availability,
    planner=_thomas_plan,
    default_model="",
    priority=0,
    mismatch_hint="",
    reaches=_thomas_reaches,
    unreachable_hint=ANTHROPIC_KEY_MISSING_MSG,
)

CLAUDE_CODE_AGENT = CodingAgentSpec(
    id="claude_code",
    label="Claude Code",
    summary="Anthropic's Claude Code CLI, headless, on Thomas's tool policy and MCP bridge.",
    dispatch="thomas.forge.anvil.agent_passes:run_claude_code_pass",
    model_families=("claude",),
    availability=_claude_code_availability,
    planner=_claude_code_plan,
    default_model="sonnet",
    priority=10,
    mismatch_hint="Claude Code runs Claude models only. Pick Thomas to run a GPT model.",
)

#: Every shipped agent, in the order they were added. Priority, not this order,
#: decides the picker and the tie-break.
BUILTIN_AGENTS: tuple[CodingAgentSpec, ...] = (THOMAS_AGENT, CLAUDE_CODE_AGENT)
BUILTIN_AGENT_IDS: tuple[str, ...] = tuple(spec.id for spec in BUILTIN_AGENTS)
