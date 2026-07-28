"""SWEEP: autonomy responsiveness (does the setting actually change behavior?).

Drives the REAL `OrchestratorBrain.process_message` at autonomy levels 1-4 with
the SAME actionable prompt and captures, at the exact layer the model is
invoked, the instructions it receives (the delegation contract's input_context +
the memory/system context + the capability token).

KEY FINDING THIS SWEEP PROVES: autonomy_level reaches the capability TOKEN (tool
permissioning) but the model's behavioral instructions are byte-identical across
all four levels. The chatbot system prompt is a single constant that always says
"OFFER to hand it to the task manager - ask if they'd like you to." So "Max
autonomy" cannot stop Thomas from asking permission. Autonomy is cosmetic at the
conversation layer.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from _harness import FakeMemoryCoordinator, Recorder

from thomas.chat.conversation import ConversationManager
from thomas.marketplace.orchestrator import brain as brain_mod
from thomas.marketplace.orchestrator.brain import OrchestratorBrain
from thomas.marketplace.orchestrator.protocol import RouteDecision


class _CaptureSpecialist:
    """A stand-in reasoning specialist that records exactly what the model layer
    is handed, then yields a trivial reply."""

    capabilities: list[str] = []

    def __init__(self, sink: list[dict]) -> None:
        self._sink = sink

    async def execute(self, *, contract, token, prompt, conversation_context, memory_context):
        self._sink.append(
            {
                "input_context": dict(getattr(contract, "input_context", {}) or {}),
                "token_autonomy": getattr(token, "autonomy_level", None),
                "memory_context": str(memory_context or ""),
            }
        )
        yield {"type": "text", "text": "ok"}
        yield {"type": "done", "iterations": 1}


class _Registry:
    def __init__(self, specialist) -> None:
        self._s = specialist

    def get(self, specialist_id):
        return self._s

    def record_execution(self, specialist_id):
        return None


async def _capture_for_level(level: int) -> dict:
    sink: list[dict] = []
    brain = OrchestratorBrain(config=None, llm=None, memory_engine=None, registry=_Registry(_CaptureSpecialist(sink)))

    async def _route(*args, **kwargs):
        return RouteDecision(specialists=["reasoning"], reasoning="test")

    with (
        patch("thomas.marketplace.orchestrator.brain.MemoryCoordinator", FakeMemoryCoordinator),
        patch.object(OrchestratorBrain, "_classify_and_route", new=AsyncMock(side_effect=_route)),
    ):
        from _harness import FakeDispatcher

        await brain.process_message(
            session_id=f"auto-{level}",
            conversation=ConversationManager(),
            prompt="put a file on my desktop that says hello",
            dispatcher=FakeDispatcher(),
            mode="max",
            autonomy_level=level,
            send_task=lambda **kw: None,
        )
    return sink[0] if sink else {}


def _reasoning_prompt_is_static() -> tuple[bool, str]:
    """Structural check: the chatbot system prompt is one constant with ask-
    language and no autonomy branching."""
    from thomas.marketplace.specialists import reasoning

    prompt = getattr(reasoning, "THOMAS_CHATBOT_SYSTEM_PROMPT", "")
    asks = "task manager" in prompt.lower() and ("hand it" in prompt.lower() or "hand this" in prompt.lower())
    autonomy_aware = any(
        t in prompt.lower() for t in ("autonomy level", "max autonomy", "if autonomy", "level 4", "l4")
    )
    return asks and not autonomy_aware, f"len={len(prompt)} asks={asks} autonomy_aware={autonomy_aware}"


def run() -> Recorder:
    rec = Recorder("autonomy")
    brain_mod._reported_completions.clear()

    captures = {lvl: asyncio.run(_capture_for_level(lvl)) for lvl in (1, 2, 3, 4)}

    # 1) The capability token DOES receive the level (plumbing reaches dispatch).
    token_levels = {lvl: c.get("token_autonomy") for lvl, c in captures.items()}
    token_ok = all(token_levels[lvl] == lvl for lvl in (1, 2, 3, 4))
    rec.add(
        case="autonomy_level reaches the capability token",
        dimension="autonomy-fidelity",
        expected="token.autonomy_level == requested level (plumbing present)",
        actual=f"token_levels={token_levels}",
        passed=token_ok,
        severity="low",
        evidence="confirms the value is threaded as far as the token",
    )

    # 2) The MODEL-FACING instructions must DIFFER by level. If identical, autonomy
    #    is cosmetic at the conversation layer. We normalize away non-deterministic
    #    callables (the send_task closure has a fresh id per call) so we compare the
    #    ACTUAL instruction content, not object addresses.
    def _norm(c: dict) -> str:
        ic = dict(c.get("input_context") or {})
        ic = {k: ("<callable>" if callable(v) else v) for k, v in ic.items()}
        return repr((sorted(ic.items()), c.get("memory_context")))

    distinct = {_norm(c) for c in captures.values()}
    differs_by_level = len(distinct) > 1
    has_autonomy_key = any("autonomy" in (c.get("input_context") or {}) for c in captures.values())
    rec.add(
        case="model-facing instructions differ across autonomy levels",
        dimension="autonomy-fidelity",
        expected="L1..L4 should give the model materially different act-vs-ask guidance",
        actual=f"distinct_normalized_contexts={len(distinct)} (1 == byte-identical), input_context_has_autonomy_key={has_autonomy_key}",
        passed=differs_by_level,
        severity="critical",
        evidence=f"input_context keys (all levels): {sorted((captures[4].get('input_context') or {}).keys())}; callables normalized out",
    )

    # 3) The chatbot system prompt instructs the model to ASK/OFFER to hand off, and
    #    nothing in the per-turn context can lift that at high autonomy (no autonomy
    #    key reaches the model). So at Max autonomy the model is STILL told to ask.
    from thomas.marketplace.specialists import reasoning

    prompt = getattr(reasoning, "THOMAS_CHATBOT_SYSTEM_PROMPT", "")
    asks = "task manager" in prompt.lower() and ("hand it" in prompt.lower() or "hand this" in prompt.lower())
    defect_present = asks and not has_autonomy_key
    rec.add(
        case="ask/offer instruction is unconditional (not lifted at high autonomy)",
        dimension="autonomy-fidelity",
        expected="at high autonomy the model should be told to ACT without asking",
        actual=f"prompt contains ask/offer language={asks}; autonomy reaches model={has_autonomy_key} -> model told to ask at ALL levels",
        passed=not defect_present,  # defect present -> FAIL
        severity="critical",
        evidence=f"THOMAS_CHATBOT_SYSTEM_PROMPT is a {len(prompt)}-char module constant; autonomy only mentioned as a disclaimer",
    )

    # 4) The token CARRIES autonomy_level, but is it ever CONSULTED to gate tools?
    #    (adversarial-discovery finding #13). Scan the specialist + tool-exec path for
    #    any read of autonomy that gates tool access. If none, autonomy is cosmetic at
    #    the permission layer too: a low-autonomy task can still invoke shell/fs-write.
    import re
    from pathlib import Path

    from _harness import _REPO_ROOT

    # Scope to the SPECIALIST dispatch path (what V2 chat uses, where the brain issues
    # the CapabilityToken). The separate AgentLoop path DOES gate approval on autonomy
    # (loop_tool_exec.py:435), so we test the path the token actually travels: do the
    # specialists ever READ token.autonomy_level to gate tools? (adversarial #13/#12)
    scan_files = list((_REPO_ROOT / "thomas" / "marketplace" / "specialists").glob("*.py"))
    read_sites = []
    for fp in scan_files:
        try:
            for ln in fp.read_text(encoding="utf-8", errors="ignore").splitlines():
                stripped = ln.strip()
                if stripped.startswith("#"):
                    continue
                if "autonomy_level" in stripped:
                    read_sites.append(f"{fp.name}: {stripped[:80]}")
        except OSError:
            continue
    rec.add(
        case="token.autonomy_level gates tools in the specialist dispatch path",
        dimension="autonomy-fidelity",
        expected="the specialist that receives the token should consult autonomy_level before allowing fs-write/shell tools",
        actual=f"autonomy_level read-sites in thomas/marketplace/specialists/: {read_sites or 'NONE'}",
        passed=bool(read_sites),
        severity="high",
        evidence="adversarial #13/#12: token.autonomy_level never read by any specialist; ToolSpecialist (tools.py:192) swaps in the FULL registry, nullifying per-task gating. (The AgentLoop path does gate approval at loop_tool_exec.py:435 — but that is not the token path.)",
    )
    return rec


if __name__ == "__main__":
    run().console()
