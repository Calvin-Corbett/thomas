"""Unified runtime profile: autonomy (outer) × token economy (inner).

Autonomy gates what the agent is *allowed* to do:
  L1 Chat      — no tools, conversation only
  L2 Assist    — tools with approval on every action
  L3 Agent     — autonomous tool use (default)
  L4 Full Auto — unrestricted, extended iterations

Token economy shapes how much *effort* the agent expends:
  cheap   — stripped-down, single-shot, minimal overhead
  optimal — balanced context + guardrails (default)
  max     — full context stack, extended passes, retries

The two compose: autonomy sits on top, economy sits inside.
Autonomy never relaxes because economy is set to max.
Economy never overrides autonomy permissions.

Example: L2 + max = the agent asks approval for every tool call,
but within each approved action it iterates thoroughly.
L4 + cheap = full autonomy but deliberately lean execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from thomas.core.autonomy import (
    AutonomyLevelSpec,
    autonomy_spec,
    clamp_autonomy_level,
)
from thomas.core.token_economy import (
    _MAX_PASSES,
    _MIN_PASSES,
    _PASS_MULTIPLIERS,
    RuntimeOverheadPolicy,
    compute_max_passes,
    loop_context_budgets,
    loop_iteration_prompt_caps,
    loop_tool_spec_budgets,
    normalize_mode,
    normalize_token_economy_level,
    runtime_overhead_policy,
)


@dataclass(frozen=True)
class RuntimeProfile:
    """Resolved runtime profile combining autonomy + economy."""

    # ── Identity ─────────────────────────────────────────────
    autonomy_level: int
    autonomy_name: str
    economy_level: str
    run_mode: str

    # ── Autonomy layer (outer — permissions) ─────────────────
    tools_policy: str | None  # "never" | "auto" | "always" | None
    needs_approval: bool  # True for L2
    prefers_extended_iterations: bool  # True for L4
    system_directive: str  # injected autonomy prompt

    # ── Economy layer (inner — effort) ───────────────────────
    pass_range: tuple[int, int]  # (min_passes, max_passes)
    pass_multiplier: float
    overhead: RuntimeOverheadPolicy
    context_budget: int  # mode budget (tokens)
    hard_budget: int | None  # hard ceiling (None = unlimited)
    tool_count_cap: int
    tool_spec_token_cap: int
    prompt_warn_cap: int
    prompt_hard_cap: int | None

    # ── Composed behaviors ───────────────────────────────────
    effective_max_iterations: int  # final iteration count
    skills_mode: str  # "off" | "explicit" | "auto"
    include_autonomy_in_prompt: bool  # whether economy allows the directive
    clarification_bias: str  # "ask" | "minimal" | "none"

    def summary_line(self) -> str:
        """One-line human summary, e.g. 'L3 Agent · Optimal · auto'."""
        return f"L{self.autonomy_level} {self.autonomy_name} · {self.economy_level.capitalize()} · {self.run_mode}"

    def to_dict(self) -> dict[str, Any]:
        """Serializable dict for API responses and logging."""
        return {
            "autonomy_level": self.autonomy_level,
            "autonomy_name": self.autonomy_name,
            "economy_level": self.economy_level,
            "run_mode": self.run_mode,
            "tools_policy": self.tools_policy,
            "needs_approval": self.needs_approval,
            "prefers_extended_iterations": self.prefers_extended_iterations,
            "pass_range": list(self.pass_range),
            "pass_multiplier": self.pass_multiplier,
            "effective_max_iterations": self.effective_max_iterations,
            "context_budget": self.context_budget,
            "hard_budget": self.hard_budget,
            "tool_count_cap": self.tool_count_cap,
            "skills_mode": self.skills_mode,
            "include_autonomy_in_prompt": self.include_autonomy_in_prompt,
            "clarification_bias": self.clarification_bias,
            "summary": self.summary_line(),
        }


def resolve_runtime_profile(
    *,
    autonomy_level: Any = 3,
    economy_level: Any = "optimal",
    run_mode: Any = "auto",
    base_iterations: int = 10,
) -> RuntimeProfile:
    """Compose autonomy + economy into a single resolved profile.

    This is the single source of truth for "what will the agent do?"
    The loop should call this once at the start and use the result
    instead of querying autonomy and economy separately.
    """
    # ── Resolve inputs ───────────────────────────────────────
    alevel = clamp_autonomy_level(autonomy_level)
    aspec: AutonomyLevelSpec = autonomy_spec(alevel)
    elevel = normalize_token_economy_level(economy_level)
    mode = normalize_mode(run_mode, default="auto")

    # ── Economy: effort within permissions ────────────────────
    overhead = runtime_overhead_policy(elevel)
    pass_mul = _PASS_MULTIPLIERS[elevel]
    min_p = _MIN_PASSES[elevel]
    max_p = _MAX_PASSES[elevel]
    computed_passes = compute_max_passes(elevel, base_iterations)

    # ── Autonomy × economy: iteration count ──────────────────
    # L4 prefers extended iterations — boost the economy pass count
    # but stay within economy's max bound so cheap still means cheap.
    effective_max_iter = computed_passes
    if aspec.prefers_extended_iterations:
        # L4 gets the higher of: economy passes, or 3x base (capped at economy max)
        extended = min(base_iterations * 3, 32)
        effective_max_iter = max(computed_passes, min(extended, max_p))

    # ── Context budgets ──────────────────────────────────────
    ctx_budget, hard_budget, _emergency = loop_context_budgets(elevel, mode)
    tool_count, tool_spec_tokens = loop_tool_spec_budgets(elevel, mode)
    warn_cap, hard_cap = loop_iteration_prompt_caps(elevel, mode)

    # ── Composed: clarification behavior ─────────────────────
    # Autonomy L1–L2: always ask. L3: minimal. L4: none.
    # Economy cheap: bias toward fewer questions.
    if alevel <= 2:
        clar_bias = "ask"
    elif alevel == 4:
        clar_bias = "none"
    elif elevel == "cheap":
        clar_bias = "minimal"
    else:
        clar_bias = "minimal"

    # ── Composed: should autonomy directive be in the prompt? ─
    # Economy controls this — cheap strips it to save tokens,
    # but autonomy enforcement still happens server-side.
    include_autonomy = bool(overhead.include_autonomy_profile)

    return RuntimeProfile(
        autonomy_level=alevel,
        autonomy_name=aspec.name,
        economy_level=elevel,
        run_mode=mode,
        tools_policy=aspec.force_tools_policy,
        needs_approval=(alevel == 2),
        prefers_extended_iterations=aspec.prefers_extended_iterations,
        system_directive=aspec.system_directive,
        pass_range=(min_p, max_p),
        pass_multiplier=pass_mul,
        overhead=overhead,
        context_budget=ctx_budget,
        hard_budget=hard_budget,
        tool_count_cap=tool_count,
        tool_spec_token_cap=tool_spec_tokens,
        prompt_warn_cap=warn_cap,
        prompt_hard_cap=hard_cap,
        effective_max_iterations=effective_max_iter,
        skills_mode=str(overhead.runtime_skills_mode or "off").strip().lower(),
        include_autonomy_in_prompt=include_autonomy,
        clarification_bias=clar_bias,
    )


# ── Convenience: full matrix for debugging / UI ──────────────


def all_profiles(base_iterations: int = 10) -> list[dict[str, Any]]:
    """Return every autonomy × economy combination as dicts.

    Useful for the Token Economy UI to show the full interaction matrix.
    """
    from thomas.core.token_economy import TOKEN_ECONOMY_LEVELS

    results: list[dict[str, Any]] = []
    for alevel in (1, 2, 3, 4):
        for elevel in TOKEN_ECONOMY_LEVELS:
            p = resolve_runtime_profile(
                autonomy_level=alevel,
                economy_level=elevel,
                base_iterations=base_iterations,
            )
            results.append(p.to_dict())
    return results
