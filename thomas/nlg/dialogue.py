"""Dialogue generation: interactive text generation.

Implements dialogue generation including:
- Dialogue act types
- Dialogue state tracking
- Response generation
- Turn-taking management
- Politeness strategies
- Topic management
- Small talk generation
"""

from dataclasses import dataclass, field
from enum import Enum

from thomas.nlg._exceptions import NLGException


class DialogueError(NLGException):
    """Raised when dialogue generation fails."""

    pass


class DialogueAct(Enum):
    """Dialogue act classifications."""

    INFORM = "inform"
    REQUEST = "request"
    QUESTION = "question"
    CONFIRM = "confirm"
    DENY = "deny"
    AGREE = "agree"
    DISAGREE = "disagree"
    GREET = "greet"
    GOODBYE = "goodbye"
    THANK = "thank"
    APOLOGY = "apology"
    CLARIFY = "clarify"
    SUGGEST = "suggest"


class Politeness(Enum):
    """Politeness levels."""

    DIRECT = "direct"
    POLITE = "polite"
    VERY_POLITE = "very_polite"


@dataclass
class DialogueState:
    """Dialogue state tracker."""

    dialogue_id: str
    turn_count: int = 0
    last_speaker: str | None = None
    discussed_topics: list[str] = field(default_factory=list)
    active_topic: str | None = None
    requests: list[str] = field(default_factory=list)
    confirmations: dict[str, bool] = field(default_factory=dict)

    def add_topic(self, topic: str) -> None:
        """Add discussed topic."""
        if topic not in self.discussed_topics:
            self.discussed_topics.append(topic)
        self.active_topic = topic

    def shift_topic(self, topic: str) -> None:
        """Shift to new topic."""
        self.add_topic(topic)

    def close_topic(self) -> None:
        """Close current topic."""
        self.active_topic = None

    def add_request(self, request: str) -> None:
        """Add pending request."""
        self.requests.append(request)

    def confirm(self, item: str, confirmed: bool = True) -> None:
        """Confirm or deny an item."""
        self.confirmations[item] = confirmed


@dataclass
class DialogueTurn:
    """Single dialogue turn."""

    speaker: str
    act: DialogueAct
    content: str
    topic: str | None = None
    politeness: Politeness = Politeness.POLITE
    previous_turn_id: int | None = None


class DialogueGenerator:
    """Generates dialogue responses.

    Implements dialogue generation with turn-taking, politeness,
    topic management, and response selection.
    """

    def __init__(self) -> None:
        """Initialize dialogue generator."""
        self.states: dict[str, DialogueState] = {}
        self.dialogue_templates: dict[DialogueAct, list[str]] = {}
        self.politeness_markers: dict[Politeness, list[str]] = {}
        self.politeness_level: Politeness = Politeness.POLITE
        self._load_default_templates()

    def _load_default_templates(self) -> None:
        """Load dialogue act templates."""
        self.dialogue_templates[DialogueAct.GREET] = [
            "Hello, how can I help you?",
            "Hi there! What can I do for you?",
            "Good day. How may I assist?",
        ]

        self.dialogue_templates[DialogueAct.GOODBYE] = [
            "Goodbye! Have a great day.",
            "See you later!",
            "Thanks for talking with me.",
        ]

        self.dialogue_templates[DialogueAct.INFORM] = [
            "I'd like to tell you that {content}",
            "Just so you know, {content}",
            "{content}",
        ]

        self.dialogue_templates[DialogueAct.REQUEST] = [
            "Could you please {content}?",
            "Would you mind {content}?",
            "Can you {content}?",
        ]

        self.dialogue_templates[DialogueAct.QUESTION] = [
            "What do you think about {content}?",
            "Can you tell me about {content}?",
            "{content}?",
        ]

        self.dialogue_templates[DialogueAct.CONFIRM] = [
            "So you're saying {content}?",
            "Just to confirm, {content}?",
            "You mean {content}?",
        ]

        self.dialogue_templates[DialogueAct.THANK] = [
            "Thank you!",
            "Thanks a lot!",
            "I appreciate that!",
        ]

        self.dialogue_templates[DialogueAct.APOLOGY] = [
            "I'm sorry, {content}",
            "My apologies, {content}",
            "Sorry about that, {content}",
        ]

        self.politeness_markers[Politeness.DIRECT] = ["", ""]

        self.politeness_markers[Politeness.POLITE] = ["please", "if you don't mind"]

        self.politeness_markers[Politeness.VERY_POLITE] = [
            "would you be so kind as to",
            "I would greatly appreciate it if you would",
        ]

    def init_dialogue(self, dialogue_id: str) -> None:
        """Initialize dialogue state.

        Args:
            dialogue_id: Dialogue identifier

        Raises:
            DialogueError: If initialization fails
        """
        if not dialogue_id:
            raise DialogueError("Empty dialogue ID")

        self.states[dialogue_id] = DialogueState(dialogue_id=dialogue_id)

    def get_state(self, dialogue_id: str) -> DialogueState | None:
        """Get dialogue state.

        Args:
            dialogue_id: Dialogue identifier

        Returns:
            Dialogue state or None
        """
        return self.states.get(dialogue_id)

    def generate_greeting(self, dialogue_id: str, speaker: str = "System") -> str:
        """Generate greeting.

        Args:
            dialogue_id: Dialogue identifier
            speaker: Speaker name

        Returns:
            Greeting text

        Raises:
            DialogueError: If generation fails
        """
        state = self.get_state(dialogue_id)
        if not state:
            raise DialogueError(f"Unknown dialogue: {dialogue_id}")

        templates = self.dialogue_templates.get(DialogueAct.GREET, [])
        if not templates:
            raise DialogueError("No greeting templates")

        response = templates[0]
        state.last_speaker = speaker
        state.turn_count += 1

        return response

    def generate_response(
        self,
        dialogue_id: str,
        user_act: DialogueAct,
        content: str = "",
        speaker: str = "System",
    ) -> str:
        """Generate dialogue response.

        Args:
            dialogue_id: Dialogue identifier
            user_act: User dialogue act
            content: Content/topic
            speaker: Speaker name

        Returns:
            Response text

        Raises:
            DialogueError: If generation fails
        """
        state = self.get_state(dialogue_id)
        if not state:
            raise DialogueError(f"Unknown dialogue: {dialogue_id}")

        # Select appropriate response act
        response_act = self._select_response_act(user_act, content)

        # Generate response
        response = self._generate_from_template(response_act, content)

        # Update state
        state.last_speaker = speaker
        state.turn_count += 1

        if content:
            state.add_topic(content)

        return response

    def _select_response_act(self, user_act: DialogueAct, content: str) -> DialogueAct:
        """Select appropriate response dialogue act.

        Args:
            user_act: User's dialogue act
            content: Content/topic

        Returns:
            Response dialogue act
        """
        # Response mappings
        response_map = {
            DialogueAct.GREET: DialogueAct.GREET,
            DialogueAct.GOODBYE: DialogueAct.GOODBYE,
            DialogueAct.QUESTION: DialogueAct.INFORM,
            DialogueAct.REQUEST: DialogueAct.CONFIRM,
            DialogueAct.THANK: DialogueAct.THANK,
        }

        return response_map.get(user_act, DialogueAct.INFORM)

    def _generate_from_template(self, act: DialogueAct, content: str = "") -> str:
        """Generate response from template.

        Args:
            act: Dialogue act
            content: Content for template

        Returns:
            Generated response
        """
        templates = self.dialogue_templates.get(act, [])
        if not templates:
            return "I understand."

        template = templates[0]

        # Fill in content
        if "{content}" in template:
            template = template.replace("{content}", content)

        # Add politeness markers
        if self.politeness_level != Politeness.DIRECT:
            markers = self.politeness_markers.get(self.politeness_level, [])
            if markers:
                template = markers[0] + " " + template

        return template

    def manage_topic(self, dialogue_id: str, topic: str, action: str = "shift") -> None:
        """Manage conversation topic.

        Args:
            dialogue_id: Dialogue identifier
            topic: Topic to manage
            action: "shift", "continue", or "close"

        Raises:
            DialogueError: If management fails
        """
        state = self.get_state(dialogue_id)
        if not state:
            raise DialogueError(f"Unknown dialogue: {dialogue_id}")

        if action == "shift":
            state.shift_topic(topic)
        elif action == "continue":
            state.add_topic(topic)
        elif action == "close":
            state.close_topic()
        else:
            raise DialogueError(f"Unknown action: {action}")

    def add_politeness(self, text: str, level: Politeness = Politeness.POLITE) -> str:
        """Add politeness markers to text.

        Args:
            text: Text to enhance
            level: Politeness level

        Returns:
            Polite text
        """
        self.politeness_level = level

        markers = self.politeness_markers.get(level, [])
        if not markers:
            return text

        # Add marker at beginning
        marker = markers[0]
        if level == Politeness.DIRECT:
            return text

        return f"{marker} {text}"

    def generate_small_talk(self, topic: str | None = None) -> str:
        """Generate small talk.

        Args:
            topic: Small talk topic

        Returns:
            Small talk text
        """
        small_talk = [
            "Nice weather today, isn't it?",
            "How has your day been?",
            "That's interesting! Tell me more.",
            "I see what you mean.",
            "That sounds great!",
            "I completely agree.",
            "How's everything going?",
        ]

        return small_talk[0] if not topic else f"That's interesting about {topic}."

    def confirm_understanding(self, dialogue_id: str, item: str) -> str:
        """Generate confirmation question.

        Args:
            dialogue_id: Dialogue identifier
            item: Item to confirm

        Returns:
            Confirmation text

        Raises:
            DialogueError: If generation fails
        """
        state = self.get_state(dialogue_id)
        if not state:
            raise DialogueError(f"Unknown dialogue: {dialogue_id}")

        templates = self.dialogue_templates.get(DialogueAct.CONFIRM, [])
        if not templates:
            return f"Did you mean {item}?"

        template = templates[0]
        response = template.replace("{content}", item)

        return response

    def deny_request(self, reason: str | None = None) -> str:
        """Generate denial response.

        Args:
            reason: Reason for denial

        Returns:
            Denial text
        """
        denials = [
            "I'm afraid I can't help with that.",
            "That's not possible.",
            "I don't think that's feasible.",
        ]

        response = denials[0]
        if reason:
            response += f" {reason}"

        return response

    def handle_turn_taking(self, dialogue_id: str, current_speaker: str) -> bool:
        """Check if it's appropriate turn for speaker.

        Args:
            dialogue_id: Dialogue identifier
            current_speaker: Current speaker

        Returns:
            True if it's valid turn

        Raises:
            DialogueError: If dialogue not found
        """
        state = self.get_state(dialogue_id)
        if not state:
            raise DialogueError(f"Unknown dialogue: {dialogue_id}")

        # Simple turn-taking: alternate speakers
        if state.last_speaker is None:
            return True

        if state.last_speaker != current_speaker:
            return True

        return False

    def get_dialogue_summary(self, dialogue_id: str) -> str:
        """Get summary of dialogue so far.

        Args:
            dialogue_id: Dialogue identifier

        Returns:
            Dialogue summary

        Raises:
            DialogueError: If dialogue not found
        """
        state = self.get_state(dialogue_id)
        if not state:
            raise DialogueError(f"Unknown dialogue: {dialogue_id}")

        summary_parts = [f"Turn {state.turn_count}"]

        if state.discussed_topics:
            summary_parts.append(f"Topics: {', '.join(state.discussed_topics)}")

        if state.active_topic:
            summary_parts.append(f"Current topic: {state.active_topic}")

        if state.requests:
            summary_parts.append(f"Pending requests: {len(state.requests)}")

        return ". ".join(summary_parts)
