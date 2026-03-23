"""Voice control integration and natural language processing."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from thomas.marketplace.smart_home._exceptions import (
    CommandDisambiguationError,
    CommandExecutionError,
    IntentParsingError,
)


@dataclass
class Intent:
    """Parsed voice intent."""

    intent_id: str
    """Unique intent ID."""
    intent_type: str
    """Intent type: turn_on, turn_off, set_brightness, etc."""
    confidence: float
    """Confidence 0-1."""
    entities: dict[str, Any] = field(default_factory=dict)
    """Named entities extracted from command."""
    device_ids: list[str] = field(default_factory=list)
    """Matched device IDs."""
    timestamp: datetime = field(default_factory=datetime.now)
    """When intent was parsed."""
    raw_text: str | None = None
    """Original voice text."""


@dataclass
class CommandMatch:
    """Potential command match."""

    device_id: str
    """Matched device ID."""
    device_name: str
    """Device name."""
    confidence: float
    """Confidence 0-1."""
    reason: str
    """Why this match was selected."""


@dataclass
class CommandHistory:
    """Voice command history entry."""

    command_id: str
    """Unique command ID."""
    original_text: str
    """Original voice input."""
    parsed_intent: Intent
    """Parsed intent."""
    executed: bool = False
    """Whether command was executed."""
    result: str | None = None
    """Command result."""
    error: str | None = None
    """Error if command failed."""
    timestamp: datetime = field(default_factory=datetime.now)
    """When command was issued."""


class VoiceController:
    """Voice control integration with NLU and context awareness.

    Provides intent parsing with slot filling, command routing to devices,
    disambiguation dialogs, context-aware commands with location awareness,
    and command history tracking.
    """

    def __init__(self) -> None:
        """Initialize voice controller."""
        self._intents_handlers: dict[str, Callable] = {}
        self._device_registry: dict[str, Any] = {}
        self._command_history: list[CommandHistory] = []
        self._context: dict[str, Any] = {}
        self._disambiguation_callbacks: list[Callable] = []
        self._intent_patterns: dict[str, list[str]] = self._init_patterns()
        self._user_location: str | None = None

    def _init_patterns(self) -> dict[str, list[str]]:
        """Initialize intent patterns.

        Returns:
            Intent type -> pattern list.
        """
        return {
            "turn_on": [
                r"turn on (?P<device>.*)",
                r"switch on (?P<device>.*)",
                r"enable (?P<device>.*)",
                r"(?P<device>.*) on",
            ],
            "turn_off": [
                r"turn off (?P<device>.*)",
                r"switch off (?P<device>.*)",
                r"disable (?P<device>.*)",
                r"(?P<device>.*) off",
            ],
            "set_brightness": [
                r"set (?P<device>.*) brightness to (?P<value>\d+)",
                r"dim (?P<device>.*) to (?P<value>\d+)",
                r"brighten (?P<device>.*) to (?P<value>\d+)",
            ],
            "set_temperature": [
                r"set (?P<zone>.*) temperature to (?P<value>\d+)",
                r"heat (?P<zone>.*) to (?P<value>\d+)",
                r"cool (?P<zone>.*) to (?P<value>\d+)",
            ],
            "activate_scene": [
                r"activate (?P<scene>.*) scene",
                r"set scene to (?P<scene>.*)",
                r"(?P<scene>.*) mode",
            ],
        }

    def register_device(self, device_id: str, name: str, aliases: list[str] | None = None) -> None:
        """Register a device for voice control.

        Args:
            device_id: Device identifier.
            name: Primary device name.
            aliases: Alternative names for the device.
        """
        self._device_registry[device_id] = {"name": name, "aliases": aliases or [], "timestamp": datetime.now()}

    def parse_intent(self, text: str) -> Intent:
        """Parse voice text into intent.

        Args:
            text: Voice input text.

        Returns:
            Parsed intent.

        Raises:
            IntentParsingError: If parsing fails.
        """
        import re

        try:
            text_lower = text.lower()
            best_intent = None
            best_confidence = 0.0

            # Try matching each intent pattern
            for intent_type, patterns in self._intent_patterns.items():
                for pattern in patterns:
                    match = re.search(pattern, text_lower)
                    if match:
                        # Calculate confidence based on pattern specificity
                        confidence = min(1.0, 0.8 + len(pattern) / 100.0)

                        if confidence > best_confidence:
                            best_confidence = confidence
                            best_intent = intent_type
                            entities = match.groupdict()

            if not best_intent:
                raise IntentParsingError(f"No intent recognized: {text}")

            intent = Intent(
                intent_id=str(uuid.uuid4()),
                intent_type=best_intent,
                confidence=best_confidence,
                entities=entities,
                raw_text=text,
            )

            # Try to resolve devices mentioned
            intent.device_ids = self._resolve_device_names(intent.entities.get("device", ""))

            return intent

        except Exception as e:
            raise IntentParsingError(f"Intent parsing failed: {e}")

    def _resolve_device_names(self, device_text: str) -> list[str]:
        """Resolve device names from text.

        Args:
            device_text: Text containing device reference.

        Returns:
            List of matching device IDs.
        """
        matches = []
        device_text_lower = device_text.lower().strip()

        for device_id, info in self._device_registry.items():
            name_match = device_text_lower == info["name"].lower()
            alias_match = any(device_text_lower == alias.lower() for alias in info.get("aliases", []))

            if name_match or alias_match:
                matches.append(device_id)

        return matches

    def disambiguate(self, candidates: list[CommandMatch]) -> CommandMatch:
        """Handle ambiguous command matches.

        Args:
            candidates: List of potential matches.

        Returns:
            Selected match.

        Raises:
            CommandDisambiguationError: If cannot disambiguate.
        """
        if not candidates:
            raise CommandDisambiguationError("No candidates to disambiguate")

        if len(candidates) == 1:
            return candidates[0]

        # Use location context to disambiguate
        if self._user_location:
            for candidate in candidates:
                if candidate.device_id.startswith(self._user_location):
                    return candidate

        # Use confidence
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        if candidates[0].confidence > 0.9:
            return candidates[0]

        # Call disambiguation callbacks
        for callback in self._disambiguation_callbacks:
            try:
                result = callback(candidates)
                if result:
                    return result
            except Exception:  # REVIEWED: broad catch
                pass

        raise CommandDisambiguationError(f"Cannot disambiguate between {len(candidates)} options")

    def set_user_location(self, location: str) -> None:
        """Set user location for context-aware commands.

        Args:
            location: Room or zone name.
        """
        self._user_location = location

    def get_user_location(self) -> str | None:
        """Get user location.

        Returns:
            Location or None.
        """
        return self._user_location

    def execute_command(self, intent: Intent) -> dict[str, Any]:
        """Execute a voice command.

        Args:
            intent: Intent to execute.

        Returns:
            Execution result.

        Raises:
            CommandExecutionError: If execution fails.
        """
        try:
            handler = self._intents_handlers.get(intent.intent_type)
            if not handler:
                raise CommandExecutionError(f"No handler for {intent.intent_type}")

            result = handler(intent)
            return result

        except Exception as e:
            raise CommandExecutionError(f"Command execution failed: {e}")

    def register_intent_handler(self, intent_type: str, handler: Callable) -> None:
        """Register handler for intent type.

        Args:
            intent_type: Intent type.
            handler: Handler callable.
        """
        self._intents_handlers[intent_type] = handler

    def register_disambiguation_callback(self, callback: Callable) -> None:
        """Register callback for command disambiguation.

        Args:
            callback: Callable(candidates) -> CommandMatch.
        """
        self._disambiguation_callbacks.append(callback)

    def process_voice_input(self, text: str) -> dict[str, Any]:
        """Process voice input end-to-end.

        Args:
            text: Voice input text.

        Returns:
            Result dict with command execution status.
        """
        command_id = str(uuid.uuid4())

        try:
            # Parse intent
            intent = self.parse_intent(text)

            # Handle potential disambiguation
            candidates = self._find_device_matches(intent)
            if len(candidates) > 1:
                try:
                    best_match = self.disambiguate(candidates)
                    intent.device_ids = [best_match.device_id]
                except CommandDisambiguationError:
                    # Ask user
                    return {
                        "status": "disambiguation_needed",
                        "candidates": [
                            {"device_id": c.device_id, "device_name": c.device_name, "confidence": c.confidence}
                            for c in candidates
                        ],
                    }

            # Execute command
            result = self.execute_command(intent)

            # Log to history
            history = CommandHistory(
                command_id=command_id, original_text=text, parsed_intent=intent, executed=True, result=str(result)
            )
            self._command_history.append(history)

            return {"status": "success", "command_id": command_id, "intent": intent.intent_type, "result": result}

        except Exception as e:
            history = CommandHistory(
                command_id=command_id, original_text=text, parsed_intent=None, executed=False, error=str(e)
            )
            self._command_history.append(history)

            return {"status": "error", "command_id": command_id, "error": str(e)}

    def _find_device_matches(self, intent: Intent) -> list[CommandMatch]:
        """Find device matches for intent.

        Args:
            intent: Parsed intent.

        Returns:
            List of potential matches.
        """
        matches = []

        for device_id in intent.device_ids:
            info = self._device_registry.get(device_id)
            if info:
                match = CommandMatch(
                    device_id=device_id, device_name=info["name"], confidence=intent.confidence, reason="name_match"
                )
                matches.append(match)

        return matches

    def generate_response(self, intent: Intent, result: dict[str, Any]) -> str:
        """Generate natural language response.

        Args:
            intent: Intent executed.
            result: Execution result.

        Returns:
            Natural language response.
        """
        device_id = intent.device_ids[0] if intent.device_ids else None
        device_name = self._device_registry.get(device_id, {}).get("name", "device") if device_id else "device"

        responses = {
            "turn_on": f"Turned on the {device_name}",
            "turn_off": f"Turned off the {device_name}",
            "set_brightness": f"Set brightness to {intent.entities.get('value', '?')}%",
            "set_temperature": f"Set temperature to {intent.entities.get('value', '?')}°C",
            "activate_scene": f"Activated {intent.entities.get('scene', 'scene')}",
        }

        return responses.get(intent.intent_type, "Command executed")

    def get_command_history(self, limit: int = 50) -> list[CommandHistory]:
        """Get voice command history.

        Args:
            limit: Maximum commands to return.

        Returns:
            List of commands.
        """
        return self._command_history[-limit:]

    def get_device_by_alias(self, alias: str) -> str | None:
        """Find device by name or alias.

        Args:
            alias: Device name or alias.

        Returns:
            Device ID or None.
        """
        alias_lower = alias.lower()

        for device_id, info in self._device_registry.items():
            if alias_lower == info["name"].lower():
                return device_id
            if any(alias_lower == a.lower() for a in info.get("aliases", [])):
                return device_id

        return None

    def set_context(self, key: str, value: Any) -> None:
        """Set context for command interpretation.

        Args:
            key: Context key.
            value: Context value.
        """
        self._context[key] = value

    def get_context(self, key: str) -> Any | None:
        """Get context value.

        Args:
            key: Context key.

        Returns:
            Context value or None.
        """
        return self._context.get(key)

    def clear_context(self) -> None:
        """Clear all context."""
        self._context.clear()

    def get_recognized_commands(self) -> dict[str, list[str]]:
        """Get list of recognized commands.

        Returns:
            Intent type -> example commands.
        """
        return self._intent_patterns.copy()

    def add_custom_intent(self, intent_type: str, patterns: list[str], handler: Callable) -> None:
        """Add custom intent type.

        Args:
            intent_type: Intent type name.
            patterns: Regex patterns.
            handler: Handler callable.
        """
        self._intent_patterns[intent_type] = patterns
        self._intents_handlers[intent_type] = handler
