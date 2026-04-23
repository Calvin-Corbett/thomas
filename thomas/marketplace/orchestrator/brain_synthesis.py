"""Routing and synthesis helpers for orchestrator brain."""

from __future__ import annotations

import json
import logging
from typing import Any

from thomas.chat.memory_layers import MemoryContext
from thomas.marketplace.orchestrator.brain_helpers import is_deterministic_tools_route
from thomas.marketplace.orchestrator.protocol import DelegationResult, RouteDecision
from thomas.marketplace.orchestrator.registry import SpecialistRegistry


async def call_brain_llm(
    llm: Any,
    messages: list[dict[str, Any]],
    max_tokens: int = 1_000,
    *,
    logger: logging.Logger,
) -> str:
    """Call the brain's LLM (for routing, synthesis, etc.)."""
    _ = max_tokens
    try:
        if hasattr(llm, "chat"):
            response = await llm.chat(messages=messages)
            if isinstance(response, dict):
                return str(response.get("text", ""))
            if hasattr(response, "content"):
                return str(response.content)
            return str(response)
        if hasattr(llm, "complete"):
            prompt_text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            response = await llm.complete(prompt=prompt_text)
            return str(response)
        logger.error("LLM client has no chat() or complete() method")
        return ""
    except Exception as exc:
        logger.error("Brain LLM call failed: %s", exc)
        raise


async def classify_and_route(
    llm: Any,
    registry: SpecialistRegistry,
    prompt: str,
    memory_ctx: MemoryContext,
    *,
    logger: logging.Logger,
) -> RouteDecision:
    """Use the brain's LLM to classify intent and decide routing."""
    _ = memory_ctx
    available = registry.specialist_ids
    if not available:
        return RouteDecision(
            specialists=["reasoning"],
            reasoning="No specialists available; using default reasoning.",
        )

    if is_deterministic_tools_route(prompt, available):
        return RouteDecision(
            specialists=["tools"],
            parallel=False,
            reasoning="Deterministic tools route for explicit file or tool request.",
            confidence=0.98,
        )

    routing_prompt = registry.build_routing_prompt(prompt)

    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Thomas's orchestrator brain. Your job is to classify "
                    "the user's intent and route to the best specialist. "
                    "Available specialists are listed below. "
                    "Respond ONLY with valid JSON."
                ),
            },
            {"role": "user", "content": routing_prompt},
        ]
        response = await call_brain_llm(llm, messages, max_tokens=300, logger=logger)
        try:
            decision = json.loads(response)
            specialists = [s for s in decision.get("specialists", []) if s in available]
            if not specialists:
                specialists = [available[0]]
            return RouteDecision(
                specialists=specialists,
                parallel=decision.get("parallel", False),
                reasoning=decision.get("reasoning", "LLM routing decision"),
                confidence=decision.get("confidence", 0.8),
            )
        except (json.JSONDecodeError, KeyError):
            logger.warning("Failed to parse routing response, using fallback")
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Routing LLM call failed: %s", exc)

    fallback = "reasoning" if "reasoning" in available else available[0]
    return RouteDecision(
        specialists=[fallback],
        reasoning=f"Fallback routing to {fallback}",
        confidence=0.5,
    )


async def synthesise_results(
    llm: Any,
    prompt: str,
    results: list[DelegationResult],
    memory_ctx: MemoryContext,
    mode: str,
    *,
    logger: logging.Logger,
) -> str:
    """Synthesise specialist outputs into a coherent response."""
    _ = memory_ctx
    _ = mode
    ok_results = [r for r in results if r.ok and r.content and r.content.strip()]

    if not ok_results:
        errors = [r.error for r in results if not r.ok and r.error]
        if errors:
            return "I encountered issues processing your request. " + " ".join(errors[:3])
        return (
            "I received your message but wasn't able to generate a response. "
            "Could you try rephrasing or asking in a different way?"
        )

    if len(ok_results) == 1:
        text = ok_results[0].content
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed_json = json.loads(stripped)
                logger.warning("Specialist returned raw JSON instead of text: %s", stripped[:200])
                if isinstance(parsed_json, dict):
                    for key in ("response", "content", "text", "answer", "message", "result"):
                        if key in parsed_json:
                            extracted = str(parsed_json[key]).strip()
                            if extracted:
                                return extracted
                return text
            except (ValueError, TypeError):
                pass
        return text

    parts = [f"[{r.specialist_id}]: {r.content}" for r in ok_results]
    synthesis_prompt = (
        f"The user asked: {prompt[:300]}\n\n"
        f"Multiple specialists produced these results:\n\n"
        + "\n\n---\n\n".join(parts)
        + "\n\nSynthesise these into a single, coherent response."
    )

    try:
        messages = [
            {"role": "system", "content": "You synthesise multiple specialist outputs into one coherent response."},
            {"role": "user", "content": synthesis_prompt},
        ]
        return await call_brain_llm(llm, messages, max_tokens=2_000, logger=logger)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Synthesis LLM call failed: %s", exc)
        return "\n\n".join(r.content for r in ok_results)
