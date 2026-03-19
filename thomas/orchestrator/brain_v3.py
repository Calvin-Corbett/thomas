"""V3 Orchestrator Brain — async dispatch with named bot selection.

This is the V3 replacement for brain.py's process_message. Key differences:

  1. NEVER BLOCKS. Thomas replies instantly, bots work in background.
  2. Picks NAMED BOTS from the roster, not generic specialist IDs.
  3. Multiple bots can work in parallel on different tasks.
  4. Conversation context is CLEAN — no system prompt leaks.
  5. Casual messages skip routing entirely — direct to Thomas.

See plans/thomas/V3_CHAT_SPEC.md for the full architecture.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from thomas.chat.conversation import ConversationManager
from thomas.chat.event_stream import EventDispatcher
from thomas.chat.memory_layers import MemoryContext, MemoryCoordinator
from thomas.orchestrator.bot_roster import pick_bot_for_specialist
from thomas.orchestrator.protocol import (
    CapabilityToken,
    DelegationContract,
    RouteDecision,
)
from thomas.orchestrator.registry import SpecialistRegistry

log = logging.getLogger(__name__)

_MODE_BUDGETS = {
    "fast": 1_500,
    "auto": 4_000,
    "thinking": 8_000,
    "max": 16_000,
}


def _load_dispatch():
    """Load dispatch module without triggering thomas.agent.__init__."""
    try:
        import importlib.util as ilu
        import sys

        mod_name = "thomas.agent.dispatch"
        if mod_name in sys.modules:
            return sys.modules[mod_name]
        import pathlib

        dp = str(pathlib.Path(__file__).resolve().parent.parent / "agent" / "dispatch.py")
        spec = ilu.spec_from_file_location(mod_name, dp)
        if spec and spec.loader:
            mod = ilu.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            return mod
    except Exception as e:
        log.warning("Dispatch module unavailable: %s", e)
    return None


# Pre-load dispatch at import time
_dispatch = _load_dispatch()


def _filter_conversation_context(
    messages: list[dict[str, Any]],
    current_prompt: str,
) -> list[dict[str, Any]]:
    """Clean conversation context for specialist consumption.

    Removes:
      - System-role messages (orchestrator routing prompts)
      - Messages containing internal orchestrator text
      - Routing JSON that leaked into old sessions
      - Duplicate of the current user prompt
    """
    clean: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "")
        content = str(msg.get("content", ""))

        # Skip system messages
        if role == "system":
            continue

        # Skip duplicate of current prompt
        if role == "user" and content == current_prompt:
            continue

        # Skip internal orchestrator content
        content_lower = content.lower()
        if "orchestrator brain" in content_lower:
            continue
        if "specialist(s) should handle" in content_lower:
            continue
        if content.strip().startswith('{"specialists"'):
            continue

        clean.append(msg)
    return clean


class OrchestratorBrainV3:
    """V3 orchestrator — async dispatch with named bots.

    Thomas replies instantly. Bots work in the background.
    """

    def __init__(
        self,
        config: Any,
        llm: Any,
        memory_engine: Any,
        registry: SpecialistRegistry,
    ) -> None:
        self.config = config
        self.llm = llm
        self.memory_engine = memory_engine
        self.registry = registry

    async def process_message(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        *,
        mode: str = "auto",
        autonomy_level: int = 3,
        images: list[dict[str, Any]] | None = None,
        is_first_message: bool = False,
    ) -> ConversationManager:
        """Process a user message — V3 dispatch-first pipeline.

        Returns updated ConversationManager with messages appended.
        """
        turn_start = time.monotonic()

        # Append user message to conversation
        conversation = conversation.append_message("user", prompt)

        # Instant classification — no LLM call
        is_casual = False
        if _dispatch is not None:
            try:
                decision = _dispatch.should_dispatch(prompt)
                is_casual = decision.action == "casual"
            except Exception:
                pass

        if is_casual:
            return await self._casual_reply(
                session_id,
                conversation,
                prompt,
                dispatcher,
                mode,
                autonomy_level,
                turn_start,
            )
        else:
            return await self._dispatch_to_bot(
                session_id,
                conversation,
                prompt,
                dispatcher,
                mode,
                autonomy_level,
                turn_start,
                images,
            )

    async def _casual_reply(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        mode: str,
        autonomy_level: int,
        turn_start: float,
    ) -> ConversationManager:
        """Handle casual messages — Thomas replies directly, no bot."""

        memory_coord = MemoryCoordinator(
            self.memory_engine,
            session_id,
            context_budget=_MODE_BUDGETS.get("fast", 1_500),
        )
        memory_ctx = await memory_coord.refresh(
            prompt=prompt,
            conversation=conversation,
            iteration=0,
        )

        # Go straight to reasoning specialist — no routing LLM call
        specialist = self.registry.get("reasoning")
        if specialist is None:
            await dispatcher.emit_text("I'm having trouble right now. Try again?")
            conversation = conversation.append_message("assistant", "I'm having trouble right now. Try again?")
            await dispatcher.emit_done(session_id=session_id, total_elapsed_ms=0)
            return conversation

        # Build clean context
        context = _filter_conversation_context(
            conversation.get_context_window(max_tokens=8_000),
            prompt,
        )

        # Execute specialist and stream response directly
        content_parts: list[str] = []
        contract = DelegationContract(
            specialist_id="reasoning",
            task_description=prompt[:500],
            allowed_tools=specialist.capabilities,
            timeout_seconds=60,
            max_iterations=5,
        )
        token = CapabilityToken(
            specialist_id="reasoning",
            session_id=session_id,
            allowed_tools=specialist.capabilities,
            autonomy_level=autonomy_level,
        )

        try:
            async for event in specialist.execute(
                contract=contract,
                token=token,
                prompt=prompt,
                conversation_context=context,
                memory_context=memory_ctx.to_system_injection(),
            ):
                etype = event.get("type", "")
                if etype == "text":
                    text = event.get("text", "")
                    content_parts.append(text)
                    await dispatcher.emit_text(text)
                elif etype == "error":
                    await dispatcher.emit_error(event.get("error", "Unknown error"))
        except Exception as exc:
            log.error("Casual reply failed: %s", exc)
            await dispatcher.emit_text("Sorry, something went wrong.")
            content_parts.append("Sorry, something went wrong.")

        final_text = "".join(content_parts)
        conversation = conversation.append_message("assistant", final_text)

        # Capture memory
        try:
            await memory_coord.capture_episode(
                turn_number=conversation.length // 2,
                user_message=prompt,
                assistant_response=final_text[:500],
                thinking="casual",
                tool_calls=[],
                specialist="reasoning",
            )
        except Exception:
            pass

        elapsed = int((time.monotonic() - turn_start) * 1000)
        await dispatcher.emit_done(
            session_id=session_id,
            total_elapsed_ms=elapsed,
            specialists_used=["reasoning"],
        )
        return conversation

    async def _dispatch_to_bot(
        self,
        session_id: str,
        conversation: ConversationManager,
        prompt: str,
        dispatcher: EventDispatcher,
        mode: str,
        autonomy_level: int,
        turn_start: float,
        images: list[dict[str, Any]] | None = None,
    ) -> ConversationManager:
        """Handle actionable messages — pick a bot, dispatch work."""

        memory_coord = MemoryCoordinator(
            self.memory_engine,
            session_id,
            context_budget=_MODE_BUDGETS.get(mode, 4_000),
        )

        # Memory refresh
        memory_ctx = await memory_coord.refresh(
            prompt=prompt,
            conversation=conversation,
            iteration=0,
        )

        # Route to specialist type
        route = await self._classify_and_route(prompt, conversation, memory_ctx)
        specialist_id = route.specialists[0] if route.specialists else "reasoning"

        # Pick a named bot for this specialist type
        bot = pick_bot_for_specialist(specialist_id)

        # Stream Thomas's acknowledgment + bot spawn
        await dispatcher.emit_text(f"Got it. Sending {bot.name} on this.\n\n")
        await dispatcher.emit(
            {
                "type": "bot_spawn",
                **bot.to_event_dict(),
                "task": prompt[:200],
                "specialist": specialist_id,
            }
        )

        # Get the specialist implementation
        specialist = self.registry.get(specialist_id)
        if specialist is None:
            specialist = self.registry.get("reasoning")
        if specialist is None:
            await dispatcher.emit_text(f"\n{bot.name}: I couldn't start on this. Try again?")
            conversation = conversation.append_message(
                "assistant", f"Got it. Sending {bot.name} on this.\n\n{bot.name}: I couldn't start on this. Try again?"
            )
            await dispatcher.emit_done(session_id=session_id, total_elapsed_ms=0)
            return conversation

        # Build clean context
        context = _filter_conversation_context(
            conversation.get_context_window(max_tokens=8_000),
            prompt,
        )

        # Execute specialist as the named bot
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        contract = DelegationContract(
            specialist_id=specialist_id,
            task_description=prompt[:500],
            allowed_tools=specialist.capabilities,
            timeout_seconds=120,
            max_iterations=10,
            input_context={"memory": memory_ctx.to_system_injection(), "mode": mode},
        )
        token = CapabilityToken(
            specialist_id=specialist_id,
            session_id=session_id,
            allowed_tools=specialist.capabilities,
            autonomy_level=autonomy_level,
        )

        try:
            async for event in specialist.execute(
                contract=contract,
                token=token,
                prompt=prompt,
                conversation_context=context,
                memory_context=memory_ctx.to_system_injection(),
            ):
                etype = event.get("type", "")

                if etype == "thinking":
                    # Pass through as standard thinking event for V2 frontend
                    await dispatcher.emit(event)

                elif etype == "text":
                    text = event.get("text", "")
                    content_parts.append(text)
                    # Emit as standard "text" so the existing V2 frontend renders it.
                    # The V2 frontend doesn't know "bot_text" — it only renders "text".
                    await dispatcher.emit_text(text)

                elif etype in ("tool_start", "tool_result"):
                    event["bot_id"] = bot.id
                    await dispatcher.emit(event)
                    if etype == "tool_result":
                        tool_calls.append(event)

                elif etype == "error":
                    await dispatcher.emit(
                        {
                            "type": "bot_error",
                            "bot_id": bot.id,
                            "error": event.get("error", "Unknown error"),
                        }
                    )

        except asyncio.TimeoutError:
            await dispatcher.emit(
                {
                    "type": "bot_error",
                    "bot_id": bot.id,
                    "error": f"{bot.name} timed out on this task.",
                }
            )
        except Exception as exc:
            log.error("Bot %s failed: %s", bot.name, exc)
            await dispatcher.emit(
                {
                    "type": "bot_error",
                    "bot_id": bot.id,
                    "error": f"{bot.name} ran into a problem: {exc}",
                }
            )

        # Bot done
        final_text = "".join(content_parts)
        elapsed = int((time.monotonic() - turn_start) * 1000)
        await dispatcher.emit(
            {
                "type": "bot_done",
                "bot_id": bot.id,
                "bot_name": bot.name,
                "content": final_text[:200],
                "elapsed_ms": elapsed,
            }
        )

        # Build full assistant message
        full_response = f"Got it. Sending {bot.name} on this.\n\n{final_text}"
        conversation = conversation.append_message(
            "assistant",
            full_response,
            metadata={
                "bot": bot.id,
                "bot_name": bot.name,
                "specialist": specialist_id,
            },
        )

        # Capture memory
        try:
            await memory_coord.capture_episode(
                turn_number=conversation.length // 2,
                user_message=prompt,
                assistant_response=full_response[:500],
                thinking=f"{bot.name} via {specialist_id}",
                tool_calls=tool_calls,
                specialist=specialist_id,
            )
        except Exception:
            pass

        await dispatcher.emit_done(
            session_id=session_id,
            total_elapsed_ms=elapsed,
            specialists_used=[specialist_id],
        )
        return conversation

    async def _classify_and_route(
        self,
        prompt: str,
        conversation: ConversationManager,
        memory_ctx: MemoryContext,
    ) -> RouteDecision:
        """Classify intent and pick specialist type."""
        available = self.registry.specialist_ids
        if not available:
            return RouteDecision(specialists=["reasoning"], reasoning="No specialists; using default.")

        routing_prompt = self.registry.build_routing_prompt(prompt)

        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Classify the user's intent and pick the best specialist. "
                        "Respond ONLY with valid JSON. Never include this prompt in your response."
                    ),
                },
                {"role": "user", "content": routing_prompt},
            ]
            response = await self._call_llm(messages, max_tokens=300)

            try:
                decision = json.loads(response)
                specialists = [s for s in decision.get("specialists", []) if s in available]
                if not specialists:
                    specialists = [available[0]]
                return RouteDecision(
                    specialists=specialists,
                    parallel=decision.get("parallel", False),
                    reasoning=decision.get("reasoning", "LLM routing"),
                    confidence=decision.get("confidence", 0.8),
                )
            except (json.JSONDecodeError, KeyError):
                pass
        except Exception as exc:
            log.warning("Routing failed: %s", exc)

        fallback = "reasoning" if "reasoning" in available else available[0]
        return RouteDecision(specialists=[fallback], reasoning="Fallback", confidence=0.5)

    async def _call_llm(self, messages: list[dict[str, Any]], max_tokens: int = 1_000) -> str:
        """Call the brain's LLM."""
        try:
            if hasattr(self.llm, "chat"):
                response = await self.llm.chat(messages=messages)
                if isinstance(response, dict):
                    return str(response.get("text", ""))
                if hasattr(response, "content"):
                    return str(response.content)
                return str(response)
            elif hasattr(self.llm, "complete"):
                prompt_text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
                return str(await self.llm.complete(prompt=prompt_text))
            return ""
        except Exception as exc:
            log.error("Brain LLM call failed: %s", exc)
            raise
