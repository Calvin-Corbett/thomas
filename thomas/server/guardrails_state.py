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
