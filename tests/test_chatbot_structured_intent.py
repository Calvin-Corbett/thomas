from __future__ import annotations

import pytest

from thomas.marketplace.chatbot.core import Chatbot, Intent, IntentType
from thomas.marketplace.chatbot.tools import ConversationTool


@pytest.mark.asyncio
async def test_chatbot_uses_structured_intent_instead_of_message_words() -> None:
    chatbot = Chatbot()
    chatbot.register_intent(Intent("greeting", IntentType.GREETING))

    response = await chatbot.process_message(
        "goodbye, quit, and do not greet me",
        intent_name="greeting",
    )

    assert response.intent is not None
    assert response.intent.name == "greeting"
    assert response.text == "Hello! How can I help you?"


@pytest.mark.asyncio
async def test_conversation_tool_requires_model_selected_intent() -> None:
    tool = ConversationTool()

    missing = await tool.execute(
        {
            "action": "process_message",
            "message": "hello",
        }
    )
    selected = await tool.execute(
        {
            "action": "process_message",
            "message": "hello",
            "intent_name": "farewell",
        }
    )

    assert missing.ok is False
    assert missing.error == "intent_name required"
    assert selected.ok is True
    assert selected.data["intent"] == "farewell"
    assert selected.data["text"] == "Goodbye! Have a great day!"
