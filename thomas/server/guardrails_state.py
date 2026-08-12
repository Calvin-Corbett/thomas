"""Guardrails policy state (Step 4, v1) — which guardrail groups are active and at
what strictness, plus the spend cap.

This is the POLICY layer (which guardrails apply). The AUTH layer that PIN-gates
*who* may change them is a later phase; v1 reads/writes plain state. The Vault
(safety-critical gates) is NOT represented here — it is always enforced and never
toggleable (see ``thomas.core.vault_registry``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The 7 toggleable guardrail groups (non-generic names, each telegraphing its job).
GUARDRAIL_GROUPS: tuple[str, ...] = (
    "sprawl_guard",  # file size & growth caps
    "clean_hands",  # commit & worktree hygiene
    "inspector",  # lint / boot / type checks
    "load_bearing",  # architecture & imports
    "safety_net",  # tests & exception handling
    "reach",  # tools / skills / web access
    "gatekeeper",  # tool-approval thresholds
)
GUARDRAIL_MODES: tuple[str, ...] = ("strict", "standard", "permissive")

# Top-level presets map every group to one strictness.
PRESETS: dict[str, str] = {
    "fortress": "strict",
    "guarded": "standard",
    "open": "permissive",
}


@dataclass(frozen=True)
class GuardrailsState:
    modes: dict[str, str] = field(default_factory=lambda: {g: "standard" for g in GUARDRAIL_GROUPS})
    spend_cap_tokens: int = 0  # 0 = no cap

    def mode_for(self, group: str) -> str:
        return self.modes.get(group, "standard")

    def to_dict(self) -> dict:
        return {"modes": dict(self.modes), "spend_cap_tokens": int(self.spend_cap_tokens)}


def from_preset(preset: str) -> GuardrailsState:
    """Build a state where every group is set to the preset's strictness."""
    mode = PRESETS.get(str(preset or "").strip().lower(), "standard")
    return GuardrailsState(modes={g: mode for g in GUARDRAIL_GROUPS})


def normalize_state(raw: dict | None) -> GuardrailsState:
    """Coerce stored/untrusted state into a valid GuardrailsState (unknown -> standard)."""
    raw = raw or {}
    modes_in = raw.get("modes") or {}
    modes: dict[str, str] = {}
    for group in GUARDRAIL_GROUPS:
        candidate = str(modes_in.get(group, "standard")).strip().lower()
        modes[group] = candidate if candidate in GUARDRAIL_MODES else "standard"
    try:
        cap = max(0, int(raw.get("spend_cap_tokens", 0) or 0))
    except (TypeError, ValueError):
        cap = 0
    return GuardrailsState(modes=modes, spend_cap_tokens=cap)


# ── Enforcement layer ──────────────────────────────────────────────────────
# Which groups are enforceable at RUN TIME vs COMMIT TIME:
#   reach      -> tool access (deny external/network tools)        [runtime]
#   gatekeeper -> tool-approval / risk posture (no_human_mode)      [runtime]
#   sprawl_guard / clean_hands / inspector / load_bearing / safety_net
#              -> code-quality gates honored by the commit/CI gate  [commit-time]
# The commit-time groups are exported as env (see modes_env) so the gate
# subsystem can read them; the runtime groups are applied directly below.

# reach mode -> tool deny tokens (matched by name / dotted-prefix / category).
# Local tools (shell, fs, git, code) stay available so coding tasks still work;
# `reach` only governs how far Thomas reaches OUT (web / http / remote / browser).
_REACH_DENY: dict[str, frozenset[str]] = {
    "strict": frozenset({"web", "http", "browser", "remote", "eng.web_extract"}),
    "standard": frozenset({"remote"}),
    "permissive": frozenset(),
}


def reach_deny_set(mode: str) -> frozenset[str]:
    """Tools/categories to drop from the registry for a given `reach` mode."""
    return _REACH_DENY.get(str(mode or "standard").strip().lower(), _REACH_DENY["standard"])


def gatekeeper_no_human_mode(mode: str, base: str | None) -> str | None:
    """How `gatekeeper` modulates the run's no-human approval posture.

    strict      -> "deny": approval-requiring tools (shell, push, out-of-sandbox
                   writes) are auto-denied, keeping an unattended run sandboxed.
    standard    -> unchanged (the autonomy-derived `base`).
    permissive  -> "allow": escalate to native-auth so the run isn't blocked.
    """
    m = str(mode or "standard").strip().lower()
    if m == "strict":
        return "deny"
    if m == "permissive":
        return "allow"
    return base


def build_effective_guardrails(preset: str = "", modes: dict | None = None) -> GuardrailsState:
    """Resolve the effective policy for a run.

    Precedence: explicit per-group `modes` -> a top-level `preset` -> the
    server-persisted policy -> all-standard default.
    """
    if modes:
        return normalize_state({"modes": modes})
    p = str(preset or "").strip().lower()
    if p in PRESETS:
        return from_preset(p)
    try:
        from thomas.server.guardrails_policy_store import load_guardrails_policy

        return load_guardrails_policy()
    # The store is imported lazily to keep this module free of a server-layer
    # dependency at import time: ImportError if it is not there, OSError for the
    # policy file, ValueError/TypeError for a file that will not parse or
    # normalize. All-standard defaults are the safe answer for a guardrail policy.
    except (ImportError, OSError, ValueError, TypeError):
        return GuardrailsState()


def modes_env(state: GuardrailsState) -> dict[str, str]:
    """Env vars the commit/CI gate subsystem can read to honor per-group modes."""
    env = {f"THOMAS_GUARDRAIL_{g.upper()}": state.mode_for(g) for g in GUARDRAIL_GROUPS}
    import json as _json

    env["THOMAS_GUARDRAIL_MODES"] = _json.dumps(state.modes, separators=(",", ":"))
    return env
