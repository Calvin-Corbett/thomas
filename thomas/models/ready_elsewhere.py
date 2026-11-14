"""Which models Chat could answer on right now, read from the catalog's last check.

A usage-limit message has to name what you can use instead — "there was no other
model I could choose" — and only the model catalog knows what actually answered.
That reader lives here, beside the catalog it reads, rather than in the chat
turn's failure text (``thomas/marketplace/orchestrator/response_failures.py``):
the orchestrator may not import ``thomas.models`` (``thomas/_architecture.py``),
so the names are read by whoever builds the turn and handed down to it.

Three things the catalog alone would get wrong, and this reader does not:

* Listing a connection's models costs no allowance, so a plan that is out until
  Saturday still answers the catalog's check. Naming it as the way out of the
  next limit is the sentence you were given, one limit later, so a profile the
  client is parked on is not offered.
* Your Claude plan is the one connection whose check asks it nothing: its three
  names are a constant (``thomas/models/sources/claude_cli.py``), so the catalog
  calls it ready whenever the CLI is installed, signed in or not. Every other
  connection's check spends its credential and records the refusal. A turn the
  CLI refused for want of a sign-in is remembered instead
  (``thomas/core/claude_plan.py``), and the plan is offered again as soon as it
  answers.
* The catalog carries each connection's declared model as well as the models it
  listed, and the menu shows the declared one only when there are no listed ones
  (``chat_model_picker.js``). A name the menu will not show is a name you cannot
  pick, so it is not offered either.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _resting_profiles() -> frozenset[str]:
    """The profiles that cannot answer right now: parked, out of allowance, or not signed in.

    The catalog says a connection answered when it was last asked; the park says
    it is refusing this minute. Your ChatGPT plan is out until Saturday and still
    lists its models, so without this a Claude plan limit would answer "I can
    answer on GPT-5.6 Sol meanwhile" — the spent allowance you started from.

    Both limit questions are asked, because a park after a rate limit lasts ten
    minutes at most and the limit you met ran a day and a half: on the park alone
    the same sentence came back as soon as those ten minutes were up.
    ``spent_allowances`` keeps a plan out until the reset the provider actually
    gave, and no longer. The third is the sign-in the Claude CLI's own refusal is
    the only cheap witness to, for the reason in this module's docstring.
    """
    try:
        from thomas.core.claude_plan import profiles_without_a_signin
        from thomas.core.provider_cooldowns import active_cooldowns, spent_allowances

        parked = (str(row.get("profile") or "") for row in active_cooldowns())
        return frozenset(parked) | frozenset(spent_allowances()) | profiles_without_a_signin()
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        log.debug("chat failure text: the resting profiles could not be read", exc_info=True)
        return frozenset()


def models_ready_elsewhere(config: Any, *, besides: str = "", limit: int = 3) -> tuple[str, ...]:
    """Models Chat could answer on right now, other than the profile named in ``besides``.

    Read from the catalog's last check (``thomas/models/catalog.py``) — the same
    list the model menu draws — so this names what is actually reachable rather
    than everything configured. A profile counts only when that check ANSWERED
    and did not record an error, which is why a stopped Ollama or an expired
    sign-in is never offered as the way out.
    """
    try:
        from thomas.models.catalog import load_cached_model_catalog

        payload = load_cached_model_catalog(config) or {}
    except (AttributeError, OSError, TypeError, ValueError):  # no catalog is an answer: name nothing
        log.debug("chat failure text: the model catalog could not be read", exc_info=True)
        return ()
    providers = payload.get("providers") if isinstance(payload.get("providers"), dict) else {}
    rows = [row for row in payload.get("models") or [] if isinstance(row, dict)]
    listed = {str(r.get("profile") or "") for r in rows if str(r.get("source") or "") == "live"}
    resting = _resting_profiles()
    ready: list[str] = []
    for row in rows:
        profile = str(row.get("profile") or "")
        if not profile or profile == besides or profile in resting:
            continue
        if row.get("hidden") or row.get("available") is False:
            continue
        # A connection's declared model, next to the models it listed, is not in
        # the menu: your Claude plan declares one of Anthropic's versioned ids and
        # offers opus, sonnet and haiku. Naming the id would name a model you
        # could not pick, and one that would go to Anthropic's API without a key.
        if profile in listed and str(row.get("source") or "") != "live":
            continue
        state = providers.get(profile) if isinstance(providers.get(profile), dict) else {}
        if not state.get("checked_at") or state.get("error"):
            continue
        name = str(row.get("display_name") or row.get("id") or "").strip()
        if name and name not in ready:
            ready.append(name)
    return tuple(ready[:limit])


def ranked_alternatives(
    current: str,
    surface: str,
    prefs: Any,
    config: Any,
    *,
    catalog: dict[str, Any] | None = None,
    turns: Any = (),
    resting_profiles: frozenset[str] | tuple[str, ...] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Rank ready (profile, model ID) choices without changing the active model.

    ``catalog`` is the last catalog answer and ``turns`` are Build's recorded
    conversation turns. Supplying them keeps the decision independent of disk.
    A caller can retain its current reasoning effort when applying a choice.
    """
    from thomas.core.claude_plan import CLAUDE_PLAN_MODEL_IDS, runs_on_claude_plan
    from thomas.models.protocol import is_loopback_base_url
    from thomas.models.sources import is_local_profile

    if catalog is None:
        try:
            from thomas.models.catalog import load_cached_model_catalog

            catalog = load_cached_model_catalog(config) or {}
        except (AttributeError, OSError, TypeError, ValueError):
            log.debug("ranked alternatives: the model catalog could not be read", exc_info=True)
            return ()
    if resting_profiles is None:
        resting_profiles = _resting_profiles()
    resting = frozenset(resting_profiles)
    models = getattr(config, "models", {})
    current_cfg = models.get(current)
    if current_cfg is None or surface not in {"chat", "build"}:
        return ()
    troubled_provider = str(current_cfg.provider or "").strip().lower().replace("-", "_")
    providers = catalog.get("providers") if isinstance(catalog.get("providers"), dict) else {}
    rows = [row for row in catalog.get("models") or () if isinstance(row, dict)]
    listed = {str(row.get("profile") or "") for row in rows if row.get("source") == "live"}
    cost = getattr(getattr(prefs, "advanced", None), "cost", None)
    chain = [item.strip() for item in str(getattr(cost, "model_failover_chain", "") or "").split(",") if item.strip()]
    privacy = getattr(getattr(prefs, "advanced", None), "privacy", None)
    local_only = surface == "chat" and bool(getattr(privacy, "local_only_mode", False))

    eligible: dict[str, list[str]] = {}
    plans: set[str] = set()
    for row in rows:
        profile = str(row.get("profile") or "")
        cfg = models.get(profile)
        if cfg is None or profile == current or profile in resting:
            continue
        provider = str(cfg.provider or "").strip().lower().replace("-", "_")
        if provider == troubled_provider:
            continue
        state = providers.get(profile) if isinstance(providers.get(profile), dict) else {}
        if not state.get("checked_at") or state.get("error") or row.get("hidden") or row.get("available") is False:
            continue
        if profile in listed and row.get("source") != "live":
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            continue
        base_url = str(getattr(cfg, "base_url", "") or "").strip()
        local = is_loopback_base_url(base_url) if base_url else is_local_profile(provider, cfg)
        plan = provider == "openai_codex" or runs_on_claude_plan(provider, str(cfg.api_key or ""))
        if surface == "build" and not (plan and (provider != "openai_codex" or model_id.lower().startswith("gpt-"))):
            continue
        if local_only and not local:
            continue
        if not plan and not local and profile not in chain:
            continue
        if plan:
            plans.add(profile)
        choices = eligible.setdefault(profile, [])
        if model_id not in choices:
            choices.append(model_id)

    ordered = sorted(
        eligible, key=lambda profile: (profile not in plans, chain.index(profile) if profile in chain else len(chain))
    )
    history = turns.get("turns", ()) if isinstance(turns, dict) else turns
    result = []
    for profile in ordered:
        choices = eligible[profile]
        selected = ""
        for turn in reversed(tuple(history or ())):
            if not isinstance(turn, dict) or turn.get("role") != "agent":
                continue
            requested = str(turn.get("model") or "").strip()
            model_id = requested.split(":", 1)[-1]
            prefix = requested.split(":", 1)[0] if ":" in requested else ""
            provider = str(models[profile].provider or "").strip().lower().replace("-", "_")
            if model_id in choices and (
                prefix == profile
                or (prefix == "claude" and runs_on_claude_plan(provider, str(models[profile].api_key or "")))
                or (not prefix and model_id in choices)
            ):
                selected = model_id
                break
        default = str(models[profile].model or "").strip()
        provider = str(models[profile].provider or "").strip().lower().replace("-", "_")
        if default not in choices and runs_on_claude_plan(provider, str(models[profile].api_key or "")):
            default = next(
                (alias for alias in CLAUDE_PLAN_MODEL_IDS if alias in default.lower().split("-") and alias in choices),
                default,
            )
        result.append((profile, selected or (default if default in choices else choices[0])))
    return tuple(result)
