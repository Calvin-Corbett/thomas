"""Validated settings contract for Forge Code dispatches.

Forge Code intentionally has a narrower capability envelope than general chat.
This module preserves every requested dial while separately reporting which
values the current executor applies, fixes to a safe value, or cannot honor.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from thomas.core import cage_account
from thomas.core.coding_agents import (
    ANTHROPIC_KEY_ENV,
    DEFAULT_AGENT_ID,
    AgentCannotRunModel,
    UnknownAgent,
    anthropic_api_root,
    builtin_registry,
    is_claude_model,
)
from thomas.core.coding_agents import resolve as resolve_agent
from thomas.core.file_access import file_access_spec, parse_file_access_level

from .forge_code_roles import ROLE_ENV, resolve_role_choices, resolve_roles

log = logging.getLogger(__name__)

# Wall-clock and repair budgets per token-economy dial — the single source of
# truth (forge_code_runner imports these). Real builds (games, web apps)
# regularly need >600s; a hard kill mid-build wastes the whole run and forces
# a from-scratch re-dispatch that costs more than letting it finish.
EXECUTION_TIMEOUTS_S = {"cheap": 600, "balanced": 1800, "max": 3600}
# Repair attempts are a runaway guard, not a ration. This was {1, 2, 3}: on the
# default setting the build engine got TWO tries to fix whatever it found before
# giving up and handing over broken work. A one-line undeclared-variable bug can
# easily outlive two attempts, especially when each attempt starts from scratch.
#
# Same reasoning as _RUNAWAY_GUARD_PASSES in token_economy: bounding the number of
# attempts does not save money, it spends money and then throws the result away.
# Cheap/balanced/max still differ in reasoning effort and token budget — that is
# where spending belongs.
EXECUTION_MAX_FIX_ITERS = {"cheap": 20, "balanced": 20, "max": 20}


class ForgeCodeSettingsError(ValueError):
    """Raised when a Forge Code setting is malformed or unsupported."""


_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")

# The Claude-model boundary moved to thomas/core/coding_agents/families.py when the
# agent became a separate choice from the model. It has to live there: an agent
# declares which FAMILIES it serves, so the family test is now a question the
# registry asks, and a second copy here would be a second answer. Same pattern,
# same listed-models fallback; this name stays because the module's own callers
# read well with it.
_is_claude_model = is_claude_model


_CLAUDE_SUBSTITUTE_MODEL = "sonnet"
_ANTHROPIC_CONTEXT_WINDOW = 200_000
_ANTHROPIC_MAX_TOKENS = 32_000
_REASONING = {"none", "low", "medium", "high", "xhigh", "max"}
_FILE_ACCESS = {"read_only", "workspace", "project", "pc", "full"}
_GUARDRAILS = {"open", "guarded", "fortress"}
_TOKEN_ECONOMY = {"cheap", "balanced", "max"}
_ENGINES = {"agent", "funnel"}
_GPT_CODE_CONTEXT_WINDOW = 200_000
_GPT_CODE_MAX_TOKENS = 16_384


def live_edit_allowed(*, autonomy_level: int, file_access: str) -> bool:
    """Whether a Forge run may edit files: Agent autonomy (3) and above, not read-only.

    The same gate also hands the builder ``check.run`` (tests, ruff, read-only
    git) at every guardrail, because a run that may edit must be able to check
    what it edited.
    """

    return int(autonomy_level) >= 3 and str(file_access) != "read_only"


CAGED_SHELL = (
    "a shell starting in the selected project that runs as the cage account: it cannot write Thomas's own code, "
    "and its only way onto the internet is the cage proxy's pinned hosts"
)
_OPEN_SHELL = "unsandboxed host shell starting in the selected project; enabled only because Open was selected"


def direct_shell_allowed(*, autonomy_level: int, file_access: str, guardrails: str) -> bool:
    """Whether Forge may expose a direct host shell for this exact policy.

    This is the single gate shared by the persisted capability report and both
    executors. ``guarded`` cannot mean one thing in the conversation record and
    a broader thing in the child process.
    """

    if not live_edit_allowed(autonomy_level=autonomy_level, file_access=file_access):
        return False
    guard = str(guardrails)
    # In the cage the shell runs as the cage account, fenced off the internet (thomas/core/cage_account.py), so
    # the default preset gets one there; only Fortress, the strict preset, keeps it out.
    return guard == "open" or (guard == "guarded" and cage_account.running_as_cage_account())


def _choice(value: Any, *, default: str, allowed: set[str], name: str) -> str:
    normalized = str(value if value is not None else default).strip().lower()
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ForgeCodeSettingsError(f"invalid {name}; expected one of: {choices}")
    return normalized


def _memory_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ForgeCodeSettingsError("invalid memory setting; expected a boolean")


# 5 is Autopilot. The Chat menu offers it and Build sends the menu's value. The
# runner process a Build launches (forge_code_runner) takes its choices from here:
# when these were two lists, settings accepted 5 and the runner refused it, so every
# Autopilot Build exited 2 before doing any work (2026-09-23).
AUTONOMY_LEVELS: tuple[int, ...] = (1, 2, 3, 4, 5)


def _autonomy_value(value: Any) -> int:
    # Build itself only asks whether the level is at least 3.
    try:
        autonomy = int(3 if value is None else value)
    except (TypeError, ValueError) as exc:
        raise ForgeCodeSettingsError("invalid autonomy_level; expected 1 through 5") from exc
    if autonomy not in AUTONOMY_LEVELS:
        raise ForgeCodeSettingsError("invalid autonomy_level; expected 1 through 5")
    return autonomy


def _resolve_agent(*, model_id: str, model: str, requested: str) -> tuple[str, bool, str]:
    """Which agent runs this request: ``(agent_id, somebody_picked_it, profile)``.

    An explicit pick is obeyed or refused with a sentence naming both the agent
    and the model — never swapped for a different agent, which is the substitution
    complaint that produced the picker in the first place. With no pick, the
    registry's priority order runs, so Thomas's own loop is the default wherever
    it can serve the model.

    Both refusals become ``ForgeCodeSettingsError`` so they arrive the same way
    every other bad dial does: before dispatch, as the request's own answer.
    """
    try:
        selection = resolve_agent(builtin_registry(), model_id=model_id, model=model, requested=requested)
    except (UnknownAgent, AgentCannotRunModel) as exc:
        raise ForgeCodeSettingsError(str(exc)) from exc
    return selection.spec.id, selection.picked, selection.plan.profile


def _validated_model(value: Any, *, name: str) -> str:
    normalized = str(value or "").strip()
    if normalized and not _MODEL_ID.fullmatch(normalized):
        raise ForgeCodeSettingsError(f"invalid {name}")
    return normalized


def _configured_default_model() -> str:
    """The model the top-bar chip is actually showing, resolved from server state.

    ``/api/models`` answers the chip through ``resolve_effective_model`` (env var
    -> user preferences -> project default -> first configured profile); this is
    the SAME resolution, so a request that arrives with no model lands on the
    model the owner can SEE, not on an invented one. Returns the concrete model
    id ("gpt-5.6-terra", "qwen2.5-coder:7b", ...) — the preference override when
    one is set, else the resolved profile's configured model — or "" when
    nothing at all is configured, which ``from_payload`` turns into a
    pre-dispatch refusal that names the real situation.

    Defensive by design: config or preference storage being unreadable must
    degrade to "no default" (and the honest refusal), never crash the request.
    """

    # Named rather than broad, and LOGGED: an unreadable config degrading to
    # "no default" silently would be the next invisible failure. The set covers
    # what config loading, preference storage, and resolution realistically
    # raise; anything outside it is a bug that should surface.
    _resolution_errors = (
        AttributeError,
        ImportError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    )
    try:
        from thomas.core.config import load_config
        from thomas.preferences.model_resolution import resolve_effective_model

        cfg = load_config()
        profile, model_id = resolve_effective_model(
            cfg,
            env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
            user_id="default",
            # db_path is left unset ON PURPOSE. resolve_effective_model already
            # falls back to preferences_store.get_db_path() itself
            # (`db_path or preferences_store.get_db_path()`), so reading the path
            # here only bought forge an import of thomas.preferences -- a
            # dependency the architecture does not allow forge to have -- in
            # exchange for the identical value. Storage that cannot be read still
            # degrades to "no default" and the honest refusal, as documented above.
            db_path=None,
        )
        if str(model_id or "").strip():
            return str(model_id).strip()
        entry = cfg.models.get(str(profile or "")) if getattr(cfg, "models", None) else None
        return str(getattr(entry, "model", "") or "").strip()
    except _resolution_errors:
        log.warning("default Code model could not be resolved from config", exc_info=True)
        return ""


@dataclass(frozen=True)
class ForgeCodeSettings:
    """One normalized Forge Code request and its honest capability report."""

    engine: str
    model: str
    model_id: str
    reasoning_effort: str
    autonomy_level: int
    file_access: str
    memory: bool
    guardrails: str
    token_economy: str
    family: str
    dispatch_model: str
    gpt_profile: str
    # True when the request carried NO model at all and the server filled in the
    # configured default (`_configured_default_model`). The capability report
    # uses it to say "configured_default" instead of claiming a pick was
    # "applied" that nobody made.
    model_defaulted: bool = False
    builder_model: str = ""
    reviewer_model: str = ""
    praxis_reviewer_profile: str = ""
    praxis_reviewer_model: str = ""
    # WHICH AGENT RUNS. Until 2026-09-25 there was no such field: `family` was
    # read off the model and the executor followed from it, so a Claude model
    # meant Claude Code and a GPT model meant Thomas's own loop. Nobody could ask
    # for Thomas's loop on a Claude model, which is the only arrangement that does
    # not depend on driving Claude Code with a personal subscription.
    #
    # `agent` is what runs. `family` stays what the MODEL is, which is all it ever
    # honestly described. `agent_picked` records whether a person chose, so the
    # capability report can say "applied" for a pick and name the resolution when
    # nobody made one.
    agent: str = DEFAULT_AGENT_ID
    agent_picked: bool = False
    agent_profile: str = ""
    agent_reason: str = ""  # set when the agent came from the conversation (agent_continuity.py)

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> ForgeCodeSettings:
        body = payload or {}
        engine = _choice(body.get("engine"), default="agent", allowed=_ENGINES, name="engine")
        requested_agent = str(body.get("agent") or "").strip()
        # KNOWN TRAP, MEASURED 2026-07-31, deliberately not changed here.
        #
        # An unspecified model becomes `claude:sonnet`, and `family` is read off
        # that prefix, so the run dispatches to the CLAUDE CLI. That is fine when
        # the caller means it. It is confusing when the caller had nothing to
        # send:
        #
        #   the chat profile drifted to `local` with model_id ""
        #   -> the shell had no model to put in the payload
        #   -> this default made it claude:sonnet
        #   -> claude CLI, which was not logged in on this machine
        #   -> the run died with "Not logged in - Please run /login", exited 1,
        #      wrote nothing
        #
        # And the turn was labelled `qwen2.5-coder:7b`, the LOCAL profile's
        # configured model -- a model that had no part in the run. The report
        # names the profile's model while `family` decides the executor, and
        # nothing reconciles the two, so the owner is told a local qwen model
        # produced a failure that actually came from Claude.
        #
        # The LABELLING half of that is now fixed: `recorded_model` reports the
        # executor that actually ran, and `capability_report` marks the model
        # dial "substituted" rather than "applied" when the request was rerouted.
        # That changes only what Thomas says about the run, not what runs.
        #
        # The other half is now decided too (measured cost 2026-08-05: chip
        # showing GPT-5.6 Terra, 4 ready OpenAI keys, run dispatched to an
        # unauthenticated Claude CLI, dead in 15s with its raw login prompt as
        # the user-facing error). A request that carries NO model at all no
        # longer invents `claude:sonnet`: the server resolves the configured
        # default — the same resolution `/api/models` uses to feed the chip —
        # so the executor is the model the owner can see. When nothing is
        # configured either, the request is refused HERE, before dispatch, with
        # a sentence naming the real situation instead of an executor's login
        # prompt downstream. A NAMED model, gpt or not, never consults the
        # default and keeps today's routing exactly.
        model = _validated_model(body.get("model"), name="model")
        model_id = _validated_model(body.get("model_id"), name="model_id")
        model_defaulted = False
        if not model and not model_id:
            resolved = _validated_model(_configured_default_model(), name="model")
            if not resolved:
                raise ForgeCodeSettingsError(
                    "No model selected — pick one in the top bar. "
                    "(The request carried no model and no default model is configured.)"
                )
            # Treated exactly as if the owner had named it: gpt detection,
            # dispatch routing and the substitution report all see the real
            # default, so a non-runnable default (a local qwen) is reported
            # "substituted" the same way an explicit pick would be.
            model = resolved
            model_id = resolved
            model_defaulted = True
        elif not model:
            # A model_id without a model (API callers): the legacy placeholder,
            # family still decided off model_id below.
            model = "claude:sonnet"
        reasoning = _choice(
            body.get("reasoning_effort", body.get("effort")),
            default="medium",
            allowed=_REASONING,
            name="reasoning_effort",
        )
        autonomy = _autonomy_value(body.get("autonomy_level"))
        file_access = _choice(body.get("file_access"), default="project", allowed=_FILE_ACCESS, name="file_access")
        memory = _memory_value(body.get("memory"))
        guardrails = _choice(
            body.get("thomas_guardrails", body.get("guardrails")),
            default="guarded",
            allowed=_GUARDRAILS,
            name="guardrails",
        )
        token_economy = _choice(
            body.get("token_economy"),
            default="balanced",
            allowed=_TOKEN_ECONOMY,
            name="token_economy",
        )

        lowered_model = model.lower()
        lowered_id = model_id.lower()
        gpt = lowered_id.startswith("gpt-") or lowered_model.startswith(("gpt-", "codex", "chatgpt", "openai_codex"))
        if gpt:
            try:
                role_choices = resolve_role_choices(body.get("build_roles"))
                roles = resolve_roles(role_choices)
            except (OSError, ValueError, TypeError) as exc:
                raise ForgeCodeSettingsError(f"Cannot resolve Build team models: {exc}") from exc
            praxis_reviewer = role_choices["reviewer"] or {}
            exact_model = (
                model_id if lowered_id.startswith("gpt-") else (model if lowered_model.startswith("gpt-") else "")
            )
            agent, agent_picked, agent_profile = _resolve_agent(
                model_id=model_id, model=model, requested=requested_agent
            )
            return cls(
                engine,
                model,
                exact_model,
                reasoning,
                autonomy,
                file_access,
                memory,
                guardrails,
                token_economy,
                "gpt",
                "codex:gpt",
                "forgecode" if exact_model else "openai_codex",
                model_defaulted=model_defaulted,
                builder_model=roles["builder"],
                reviewer_model=roles["reviewer"],
                praxis_reviewer_profile=str(praxis_reviewer.get("profile") or ""),
                praxis_reviewer_model=str(praxis_reviewer.get("model_id") or ""),
                agent=agent,
                agent_picked=agent_picked,
                agent_profile=agent_profile,
            )

        variant = model_id or model
        # The dispatch form is `claude:<variant>`; a value already carrying the
        # `claude:` prefix (the wire form, or a resolved `claude:sonnet`
        # default landing in model_id) must shed it here or the executor is
        # handed `claude:claude:sonnet`.
        if variant.lower().startswith("claude:"):
            variant = variant.split(":", 1)[1]
        variant = variant or _CLAUDE_SUBSTITUTE_MODEL
        # The model you picked is the model that runs. Calvin, 2026-08-14:
        # "models that cant code shouldnt be offered but the mode[l] selcted
        # should be the run doing the work".
        #
        # This used to rewrite any foreign id to the CLI's Sonnet alias and
        # report it as "substituted" — honest about the swap, but still a swap
        # nobody asked for: you chose a local qwen and Claude wrote your code.
        # Refuse instead, here, before dispatch, naming what Build can actually
        # run. A refusal you can act on beats a run you did not order.
        #
        # Build's picker filters to these same two families, so reaching this
        # message means something bypassed it (an API caller, a stale client, or
        # a configured default Build cannot execute) — all cases where guessing
        # is worse than stopping.
        if not _is_claude_model(variant):
            picked = model_id or model
            source = "your configured default model" if model_defaulted else "the selected model"
            raise ForgeCodeSettingsError(
                f"Build cannot run '{picked}' — {source} is neither a GPT model nor a Claude model. "
                "Build's agents run those two families: Thomas runs GPT through your ChatGPT account and "
                "Claude through an Anthropic key, and Claude Code runs Claude. Pick one of those for Build, "
                "or ask in Chat, which can use this model."
            )
        try:
            role_choices = resolve_role_choices(body.get("build_roles"))
        except (OSError, ValueError, TypeError) as exc:
            raise ForgeCodeSettingsError(f"Cannot resolve Build team models: {exc}") from exc
        praxis_reviewer = role_choices["reviewer"] or {}
        agent, agent_picked, agent_profile = _resolve_agent(model_id=variant, model=model, requested=requested_agent)
        return cls(
            engine,
            model,
            model_id,
            reasoning,
            autonomy,
            file_access,
            memory,
            guardrails,
            token_economy,
            "claude",
            f"claude:{variant}",
            "",
            model_defaulted=model_defaulted,
            praxis_reviewer_profile=str(praxis_reviewer.get("profile") or ""),
            praxis_reviewer_model=str(praxis_reviewer.get("model_id") or ""),
            agent=agent,
            agent_picked=agent_picked,
            agent_profile=agent_profile,
        )

    def child_environment(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """Return a child environment pinning the exact model the chosen agent runs.

        The temporary ``forgecode`` profile avoids mutating project config and is
        consumed only by the in-process AgentLoop dispatcher — Thomas's own agent.
        For GPT its provider is ``openai_codex``, an OAuth alias that reuses the
        existing ChatGPT connection you made, without copying or exposing the token.

        For Claude it is ``anthropic`` with a key, which is the arm that makes
        Thomas's own loop a real alternative to Claude Code rather than a GPT-only
        default: a product that drives Claude Code on people's personal
        subscriptions can be restricted, so the default agent needs a path to
        Claude that does not use one. ``runs_on_claude_plan`` reads an Anthropic
        profile with NO key as "this is the Claude CLI's sign-in", so the key here
        is also what keeps this profile pointed at Anthropic's API.

        Claude Code needs none of this — it carries its own sign-in — so nothing
        is pinned when it is the agent.
        """

        env = dict(base if base is not None else os.environ)
        env.pop(ROLE_ENV, None)
        if self.family == "gpt":
            env[ROLE_ENV] = json.dumps({"builder": self.builder_model, "reviewer": self.reviewer_model})
        if self.agent == DEFAULT_AGENT_ID and self.family == "gpt" and self.model_id:
            env["THOMAS_MODELS_FORGECODE_PROVIDER"] = "openai_codex"
            env["THOMAS_MODELS_FORGECODE_MODEL"] = self.model_id
            env["THOMAS_MODELS_FORGECODE_REASONING_EFFORT"] = self.reasoning_effort
            env["THOMAS_MODELS_FORGECODE_CONTEXT_WINDOW"] = str(_GPT_CODE_CONTEXT_WINDOW)
            env["THOMAS_MODELS_FORGECODE_MAX_TOKENS"] = str(_GPT_CODE_MAX_TOKENS)
        elif self.agent == DEFAULT_AGENT_ID and self.family == "claude":
            env["THOMAS_MODELS_FORGECODE_PROVIDER"] = "anthropic"
            env["THOMAS_MODELS_FORGECODE_MODEL"] = self.dispatch_model.split(":", 1)[-1]
            # ANTHROPIC_BASE_URL is the SDK's form (no /v1); the profile needs the API root.
            env["THOMAS_MODELS_FORGECODE_BASE_URL"] = anthropic_api_root(env.get("ANTHROPIC_BASE_URL"))
            env["THOMAS_MODELS_FORGECODE_CONTEXT_WINDOW"] = str(_ANTHROPIC_CONTEXT_WINDOW)
            env["THOMAS_MODELS_FORGECODE_MAX_TOKENS"] = str(_ANTHROPIC_MAX_TOKENS)
            # Re-spelling a key the child already inherits, not a new exposure:
            # `base` is this process's environ, ANTHROPIC_API_KEY is in it, and the
            # child gets the whole mapping either way. The profile field is how
            # `get_http_client` finds it (`x-api-key`), and leaving it empty is
            # what `runs_on_claude_plan` reads as "use the CLI instead".
            #
            # Read off `env`, not os.environ: an injected base is the whole truth
            # about what the child will see, and a test that builds one would
            # otherwise be answered by this process's own key. A key saved in the
            # app is not in env and is not put there: it rides the start pipe.
            key = next((str(env.get(name) or "").strip() for name in ANTHROPIC_KEY_ENV if env.get(name)), "")
            if key:
                env["THOMAS_MODELS_FORGECODE_API_KEY"] = key
        return env

    def agent_label(self) -> str:
        """The chosen agent's display name, for the report and the run record."""
        spec = builtin_registry().get(self.agent)
        return spec.label if spec is not None else self.agent

    def agent_report(self) -> dict[str, Any]:
        """The agent dial, in the same shape every other dial reports.

        ``applied`` when somebody picked it, ``resolved`` when nobody did — a
        default is not a choice, and saying "applied" about one asserts a pick
        nobody made. That distinction is the same one ``model`` already draws with
        ``configured_default``.
        """
        return {
            "status": "applied" if self.agent_picked else "resolved",
            "requested": self.agent if self.agent_picked else "",
            "effective": self.agent,
            "label": self.agent_label(),
            "profile": self.agent_profile,
            "reason": self.agent_reason
            or (
                f"{self.agent_label()} was chosen for this run."
                if self.agent_picked
                else f"No agent was picked, so Build used {self.agent_label()} — "
                f"the first installed agent that runs {self.family} models."
            ),
        }

    def runs_requested_model(self) -> bool:
        """Whether the executor really runs the model the caller asked for.

        Code has exactly two model families: GPT and Claude. Which AGENT runs them
        is now a separate choice (``self.agent``), so this stays the question it
        always was — was the model substituted — and no longer implies the
        executor. A non-GPT, non-Claude model is refused in ``from_payload``
        rather than quietly rerouted.
        """

        if self.family == "gpt":
            # A GPT/codex request handled by the GPT executor is not a
            # substitution, even when no exact `gpt-` id was pinned.
            #
            # This returned `bool(self.model_id)`, which made every
            # codex-shaped payload -- `codex`, `chatgpt`, `openai_codex`, none of
            # which start with `gpt-` -- report status "substituted" with the
            # reason "'codex' is neither, so the Claude CLI handled this
            # request". The Claude CLI handled nothing; the in-process ChatGPT
            # path did. It replaced a true label ("configured_default") with a
            # false sentence, which is the exact failure this method exists to
            # prevent.
            #
            # Whether an EXACT model was pinned is a different question, and
            # `capability_report` already answers it separately via `exact_gpt`
            # -> "configured_default".
            return True
        requested = (self.model_id or self.model).strip()
        if not requested:
            # Nothing was asked for, so nothing was substituted. The invented
            # `claude:sonnet` default is reported by `recorded_model` either way.
            return True
        if requested.lower().startswith("claude:"):
            requested = requested.split(":", 1)[1]
        return _is_claude_model(requested)

    def recorded_model(self) -> str:
        """The model a turn should be attributed to: the one that actually ran.

        `model_id` is what the OWNER picked and `dispatch_model` is what the
        executor was given. Preferring `model_id` -- which is what the turn
        recorder and this report both used to do -- labels a run with a model
        that had no part in it. Observed: profile `Local`, turn labelled
        `qwen2.5-coder:7b`, transcript ending `claude exited 1` because the
        Claude CLI is not logged in on that machine.

        GPT keeps `model_id`, because the isolated forgecode profile really is
        pinned to that exact model (`child_environment`).

        Claude reports `dispatch_model` (`claude:<variant>`) only when CLAUDE CODE
        is the agent, because there that prefix is true: it names the executor and
        the variant handed to it. When Thomas's own loop runs the Claude model, the
        prefix would name an executor that had no part in the run — the same
        mislabelling this method exists to prevent, one layer up — so the model id
        stands alone and `agent` carries who ran it.
        """

        if self.family == "claude" and self.agent != DEFAULT_AGENT_ID:
            return self.dispatch_model
        return self.model_id or self.dispatch_model.split(":", 1)[-1] or self.dispatch_model

    def requested(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "agent": self.agent if self.agent_picked else "",
            "model": self.model,
            "model_id": self.model_id,
            "reasoning_effort": self.reasoning_effort,
            "autonomy_level": self.autonomy_level,
            "file_access": self.file_access,
            "memory": self.memory,
            "guardrails": self.guardrails,
            "token_economy": self.token_economy,
            "build_roles": {
                "builder": {"profile": "openai_codex", "model_id": self.builder_model} if self.builder_model else None,
                "reviewer": (
                    {"profile": self.praxis_reviewer_profile, "model_id": self.praxis_reviewer_model}
                    if self.praxis_reviewer_profile
                    else None
                ),
            },
        }

    def execution_policy(self) -> dict[str, Any]:
        """Map every UI dial onto a bounded Forge executor behavior."""

        live_edit = live_edit_allowed(autonomy_level=self.autonomy_level, file_access=self.file_access)
        timeout = EXECUTION_TIMEOUTS_S[self.token_economy]
        max_fix_iters = EXECUTION_MAX_FIX_ITERS[self.token_economy]
        access_level = parse_file_access_level(self.file_access)
        guardrail_mode = {"open": "permissive", "guarded": "standard", "fortress": "strict"}[self.guardrails]
        return {
            "live_edit": live_edit,
            "history_enabled": self.memory,
            "allow_shell": direct_shell_allowed(
                autonomy_level=self.autonomy_level,
                file_access=self.file_access,
                guardrails=self.guardrails,
            ),
            "timeout": timeout,
            "max_fix_iters": max_fix_iters,
            "sandbox_root": "selected_project",
            "file_access": self.file_access,
            "file_access_level": access_level,
            "guardrails": self.guardrails,
            "guardrail_mode": guardrail_mode,
        }

    def capability_report(self) -> dict[str, Any]:
        exact_gpt = self.family == "gpt" and bool(self.model_id)
        reasoning_status = "applied" if exact_gpt else "unsupported"
        reasoning_reason = (
            "applied to the isolated Forge GPT profile"
            if exact_gpt
            # Named by AGENT, not by family. "the Claude executor" was one
            # sentence for one executor; there are two now, and Claude Code is the
            # one with no reasoning-effort control.
            else f"{self.agent_label()} does not expose a reasoning-effort control for Claude models"
            if self.family == "claude"
            else "an exact GPT model_id is required to apply reasoning effort safely"
        )
        effective_model = self.recorded_model()
        runs_requested = self.runs_requested_model()
        policy = self.execution_policy()
        access_spec = file_access_spec(policy["file_access_level"])
        access_reason = {
            "read_only": "read-only planning is enforced; no filesystem writes are registered",
            "workspace": "writes are confined to the selected Code workspace",
            "project": "writes are confined to the selected project",
            "pc": "writes may reach the selected project and the user's home folders",
            "full": "writes may reach non-system paths; OS directories and Thomas runtime protections remain enforced",
        }[self.file_access]
        return {
            "requested": self.requested(),
            "effective": {
                "engine": self.engine,
                "agent": self.agent,
                "agent_label": self.agent_label(),
                "model": effective_model,
                "build_roles": {
                    "manager": effective_model,
                    "builder": self.builder_model or effective_model,
                    "reviewer": self.reviewer_model or effective_model,
                    **(
                        {
                            "praxis_read_reviewer": {
                                "profile": self.praxis_reviewer_profile,
                                "model_id": self.praxis_reviewer_model,
                            }
                        }
                        if self.praxis_reviewer_profile and self.praxis_reviewer_profile != "openai_codex"
                        else {}
                    ),
                }
                if self.family == "gpt"
                else (
                    {
                        "praxis_read_reviewer": {
                            "profile": self.praxis_reviewer_profile,
                            "model_id": self.praxis_reviewer_model,
                        }
                    }
                    if self.praxis_reviewer_profile
                    else {}
                ),
                "reasoning_effort": self.reasoning_effort if reasoning_status == "applied" else None,
                "file_access": self.file_access,
                "file_access_level": policy["file_access_level"],
                "autonomy_level": self.autonomy_level,
                "memory": self.memory,
                "guardrails": self.guardrails,
                "token_economy": self.token_economy,
                "execution_policy": policy,
            },
            "support": {
                "engine": {"status": "applied"},
                "agent": self.agent_report(),
                # "applied" used to cover the whole claude family, which asserted
                # that a requested local qwen had been applied when the Claude CLI
                # ran instead. This module exists to report what the executor
                # "applies, fixes to a safe value, or cannot honor" -- for the
                # model dial it was doing the opposite.
                # "configured_default" also covers the empty-model path
                # (`model_defaulted`): the request named nothing and the server
                # applied its resolved default, so "applied" would assert a pick
                # that nobody made. A defaulted model Code cannot run still
                # reports "substituted", with the reason saying where the model
                # came from, exactly as an explicit pick would.
                "model": {
                    "status": (
                        "substituted"
                        if not runs_requested
                        else "configured_default"
                        if self.model_defaulted or (self.family == "gpt" and not exact_gpt)
                        else "applied"
                    ),
                    # An empty request asked for nothing; putting the resolved
                    # default under "requested" would fabricate that pick.
                    "requested": "" if self.model_defaulted else (self.model_id or self.model),
                    "effective": effective_model,
                    **(
                        {
                            "reason": (
                                (
                                    "No model arrived with this request, so the configured "
                                    f"default {self.model_id or self.model!r} was used. "
                                    if self.model_defaulted
                                    else ""
                                )
                                + "Build runs GPT models and Claude models. "
                                f"{self.model_id or self.model!r} is neither, so {self.agent_label()} "
                                f"handled this request as {effective_model!r}."
                            )
                        }
                        if not runs_requested
                        else {
                            "reason": (
                                "No model arrived with this request; the server applied the "
                                "configured default — the same model the top-bar chip shows."
                            )
                        }
                        if self.model_defaulted
                        else {}
                    ),
                },
                "reasoning_effort": {"status": reasoning_status, "reason": reasoning_reason},
                "file_access": {
                    "status": "applied",
                    "effective": self.file_access,
                    "level": policy["file_access_level"],
                    "label": access_spec.name,
                    "reason": access_reason,
                },
                "autonomy_level": {
                    "status": "applied",
                    "effective": "edit_and_verify" if policy["live_edit"] else "plan_only",
                },
                "memory": {
                    "status": "applied",
                    "effective": "conversation_history" if self.memory else "off",
                },
                "guardrails": {
                    "status": "applied",
                    "effective": self.guardrails,
                    "mode": policy["guardrail_mode"],
                    "terminal": "enabled_in_selected_project" if policy["allow_shell"] else "engine_verification_only",
                    "terminal_boundary": (
                        (CAGED_SHELL if cage_account.running_as_cage_account() else _OPEN_SHELL)
                        if policy["allow_shell"]
                        else "no direct shell; the engine runs bounded verification after the edit pass"
                    ),
                },
                "token_economy": {
                    "status": "applied",
                    "effective": self.token_economy,
                    "timeout": policy["timeout"],
                    "max_fix_iters": policy["max_fix_iters"],
                },
            },
        }
