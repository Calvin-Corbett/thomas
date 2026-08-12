"""Chatbot framework driven by structured intents and dialogue state."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class IntentType(str, Enum):
    """Types of intents."""

    GREETING = "greeting"
    FAREWELL = "farewell"
    HELP = "help"
    QUESTION = "question"
    REQUEST = "request"
    CLARIFICATION = "clarification"
    AFFIRMATION = "affirmation"
    NEGATION = "negation"


@dataclass
class Slot:
    """A slot for capturing entity information."""

    name: str
    slot_type: str = "string"
    value: Any | None = None
    required: bool = False
    filled: bool = False

    def fill(self, value: Any) -> None:
        """Fill the slot with a value."""
        self.value = value
        self.filled = True

    def clear(self) -> None:
        """Clear the slot."""
        self.value = None
        self.filled = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {"name": self.name, "type": self.slot_type, "value": self.value, "filled": self.filled}


@dataclass
class Intent:
    """A structured intent selected by the calling model or client."""

    name: str
    intent_type: IntentType
    confidence: float = 1.0
    slots: dict[str, Slot] = field(default_factory=dict)
    entities: list[dict[str, Any]] = field(default_factory=list)

    def add_slot(self, slot: Slot) -> None:
        """Add a slot to the intent."""
        self.slots[slot.name] = slot

    def get_unfilled_slots(self) -> list[Slot]:
        """Get all unfilled required slots."""
        return [s for s in self.slots.values() if s.required and not s.filled]

    def all_slots_filled(self) -> bool:
        """Check if all required slots are filled."""
        return len(self.get_unfilled_slots()) == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "type": self.intent_type.value,
            "confidence": self.confidence,
            "slots": {name: slot.to_dict() for name, slot in self.slots.items()},
            "entities": self.entities,
        }


class DialogueState:
    """Tracks the current dialogue state."""

    def __init__(self):
        self.id = str(uuid.uuid4())
        self.intent: Intent | None = None
        self.previous_intents: list[Intent] = []
        self.slots: dict[str, Slot] = {}
        self.context: dict[str, Any] = {}
        self.turn_count: int = 0
        self.session_start: datetime = datetime.now()

    def set_intent(self, intent: Intent) -> None:
        """Set the current intent."""
        if self.intent:
            self.previous_intents.append(self.intent)
        self.intent = intent

    def update_slot(self, slot_name: str, value: Any) -> None:
        """Update a slot value."""
        if slot_name in self.slots:
            self.slots[slot_name].fill(value)

    def get_intent_history(self) -> list[str]:
        """Get history of intents."""
        history = [i.name for i in self.previous_intents]
        if self.intent:
            history.append(self.intent.name)
        return history

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "state_id": self.id,
            "current_intent": self.intent.to_dict() if self.intent else None,
            "turn_count": self.turn_count,
            "slots": {name: slot.to_dict() for name, slot in self.slots.items()},
        }


class Response:
    """A chatbot response."""

    def __init__(self, text: str, intent: Intent | None = None):
        self.id = str(uuid.uuid4())
        self.text = text
        self.intent = intent
        self.suggested_actions: list[str] = []
        self.metadata: dict[str, Any] = {}
        self.timestamp = datetime.now()

    def add_suggested_action(self, action: str) -> None:
        """Add a suggested action."""
        self.suggested_actions.append(action)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "text": self.text,
            "intent": self.intent.name if self.intent else None,
            "suggested_actions": self.suggested_actions,
            "timestamp": self.timestamp.isoformat(),
        }


class Chatbot:
    """Main chatbot class."""

    def __init__(self, name: str = "chatbot"):
        self.id = str(uuid.uuid4())
        self.name = name
        self.intents: dict[str, Intent] = {}
        self.dialogue_state = DialogueState()
        self.conversation_history: list[tuple[str, str]] = []
        self.responses: dict[str, list[str]] = {}
        self.entities: dict[str, list[str]] = {}

    def register_intent(self, intent: Intent) -> None:
        """Register an intent."""
        self.intents[intent.name] = intent

    def register_response(self, intent_name: str, response_text: str) -> None:
        """Register a response for an intent."""
        if intent_name not in self.responses:
            self.responses[intent_name] = []
        self.responses[intent_name].append(response_text)

    def register_entity(self, entity_type: str, values: list[str]) -> None:
        """Register entity values."""
        self.entities[entity_type] = values

    async def process_message(self, message: str, *, intent_name: str) -> Response:
        """Process a message under a model-selected structured intent."""
        self.dialogue_state.turn_count += 1
        selected = str(intent_name or "").strip()
        intent = self.intents.get(selected) or Intent(selected or "unknown", IntentType.QUESTION)
        self.dialogue_state.set_intent(intent)
        response_text = self._generate_response(intent)
        self.conversation_history.append((message, response_text))
        return Response(response_text, intent)

    def _generate_response(self, intent: Intent) -> str:
        """Generate a response for the intent."""
        if intent.name in self.responses:
            responses = self.responses[intent.name]
            if responses:
                return responses[0]

        # Default responses
        defaults = {
            "greeting": "Hello! How can I help you?",
            "farewell": "Goodbye! Have a great day!",
            "help": "I'm here to help. What do you need?",
            "unknown": "I'm not sure I understand. Can you clarify?",
        }

        return defaults.get(intent.name, "I'll do my best to help!")

    def get_conversation_history(self) -> list[dict[str, str]]:
        """Get the conversation history."""
        return [{"user": user, "assistant": assistant} for user, assistant in self.conversation_history]

    def reset(self) -> None:
        """Reset the chatbot."""
        self.dialogue_state = DialogueState()
        self.conversation_history = []

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "chatbot_id": self.id,
            "name": self.name,
            "intents_registered": len(self.intents),
            "conversation_turns": len(self.conversation_history),
        }
