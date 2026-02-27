"""Conversational intelligence integration layer.

Wires together the context tracker, conversation intelligence,
and learning system into a single interface that the agent loop
can call with minimal code changes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from thomas.agent.context_tracker import ContextTracker
from thomas.agent.conversation import ConversationIntelligence

logger = logging.getLogger(__name__)

# Try to import learning system — gracefully degrade if unavailable
try:
    from thomas.learning.analyzer import ConversationAnalyzer
    from thomas.learning.feedback import FeedbackLoop
    from thomas.learning.injector import LessonInjector
    from thomas.learning.store import LessonStore

    _LEARNING_AVAILABLE = True
except ImportError:
    _LEARNING_AVAILABLE = False
    logger.debug("Learning system not available — running without it")


class IntelligenceLayer:
    """Unified conversational intelligence for the agent loop.

    Combines context tracking, conversation intelligence, and
    learned knowledge into a single update/query interface.

    Args:
        learning_enabled: Whether to use the learning system
        storage_dir: Directory for lesson/feedback persistence
    """

    def __init__(
        self,
        learning_enabled: bool = True,
        storage_dir: str | None = None,
    ) -> None:
        self._context = ContextTracker(max_turns=12, max_topics=5)
        self._conversation = ConversationIntelligence(max_turns=12)

        # Learning system (optional)
        self._learning_enabled = learning_enabled and _LEARNING_AVAILABLE
        self._lesson_store: Any | None = None
        self._injector: Any | None = None
        self._analyzer: Any | None = None
        self._feedback: Any | None = None

        if self._learning_enabled:
            try:
                store_dir = storage_dir or os.path.join(str(Path.home()), ".thomas", "learning")
                os.makedirs(store_dir, exist_ok=True)
                store_path = os.path.join(store_dir, "lessons.json")
                feedback_path = os.path.join(store_dir, "feedback.json")

                self._lesson_store = LessonStore(store_path)
                self._injector = LessonInjector()
                self._analyzer = ConversationAnalyzer()
                self._feedback = FeedbackLoop(feedback_path)
                logger.info("Learning system initialized at %s", store_dir)
            except Exception as e:
                logger.warning("Learning system init failed: %s", e)
                self._learning_enabled = False

    def update_user_message(self, text: str) -> None:
        """Process an incoming user message.

        Args:
            text: The user's message text
        """
        self._context.update("user", text)
        self._conversation.update("user", text)

    def update_assistant_message(self, text: str) -> None:
        """Process an outgoing assistant message.

        Args:
            text: The assistant's response text
        """
        self._context.update("assistant", text)
        self._conversation.update("assistant", text)

    def is_followup(self, message: str) -> bool:
        """Check if this message is a follow-up.

        Args:
            message: User message to check

        Returns:
            True if this is a follow-up
        """
        return self._conversation.is_followup(message)

    def detect_confusion(self, user_msg: str) -> bool:
        """Check if the user is confused.

        Args:
            user_msg: Current user message

        Returns:
            True if user seems confused
        """
        return self._conversation.detect_confusion(user_msg)

    def get_context_text(self) -> str:
        """Get context block text for system prompt injection.

        Returns:
            Formatted context summary
        """
        return self._context.to_prompt_block(max_chars=500)

    def get_lessons_text(self, query: str, max_lessons: int = 3) -> str:
        """Get relevant lessons for system prompt injection.

        Args:
            query: Search query (usually the user's message)
            max_lessons: Maximum lessons to retrieve

        Returns:
            Formatted lessons text
        """
        if not self._learning_enabled or not self._lesson_store:
            return ""

        try:
            lessons = self._lesson_store.search(query, limit=max_lessons)
            if not lessons:
                return ""
            lines = []
            for lesson in lessons:
                ltype = getattr(lesson, "lesson_type", "fact")
                content = getattr(lesson, "content", str(lesson))
                if hasattr(ltype, "value"):
                    ltype = ltype.value
                lines.append(f"- [{ltype}] {content}")
            return "\n".join(lines)
        except Exception as e:
            logger.debug("Lesson retrieval failed: %s", e)
            return ""

    def learn_from_interaction(
        self,
        user_message: str,
        assistant_response: str,
        quality_score: float = 0.7,
    ) -> None:
        """Store a lesson from a successful interaction.

        Args:
            user_message: What the user asked
            assistant_response: What we responded
            quality_score: Estimated quality (0.0-1.0)
        """
        if not self._learning_enabled or not self._analyzer:
            return

        try:
            if quality_score >= 0.8:
                lesson = self._analyzer.analyze_success(user_message, assistant_response, quality_score)
                if lesson and self._lesson_store:
                    self._lesson_store.add_lesson(lesson)
        except Exception as e:
            logger.debug("Learning from interaction failed: %s", e)

    def get_continuity_hint(self) -> str:
        """Get a continuity hint for routing.

        Returns:
            Brief context hint string
        """
        return self._conversation.generate_continuity_hint()

    def get_prior_route_hint(self) -> str | None:
        """Get the prior topic for route biasing.

        Returns:
            Topic string or None
        """
        return self._conversation.get_prior_route_hint()

    @property
    def current_task(self) -> str:
        """The user's current task."""
        return self._context.current_task

    @property
    def mood(self) -> str:
        """The user's detected mood."""
        return self._context.mood

    @property
    def turn_count(self) -> int:
        """Total turns processed."""
        return self._context.turn_count

    @property
    def learning_enabled(self) -> bool:
        """Whether the learning system is active."""
        return self._learning_enabled
