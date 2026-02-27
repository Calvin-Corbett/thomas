"""Tools for Chatbot module.

Provides tools for managing intents, processing messages, and dialogue management.
"""

from typing import Any

from thomas.chatbot import core
from thomas.tools.base import Tool, ToolResult


class IntentManagementTool(Tool):
    """Manage chatbot intents."""

    name = "chatbot_intents"
    category = "chatbot"
    description = "Create and manage NLU intents"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_intent", "list_intents", "register_response"],
                "description": "Intent action",
            },
            "intent_name": {"type": "string", "description": "Name of the intent"},
            "intent_type": {"type": "string", "description": "Type of intent"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.chatbot = core.Chatbot()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_intent":
                intent_name = args.get("intent_name", "intent")
                intent_type_str = args.get("intent_type", "question")

                try:
                    intent_type = core.IntentType(intent_type_str)
                except ValueError:
                    intent_type = core.IntentType.QUESTION

                intent = core.Intent(intent_name, intent_type)
                self.chatbot.register_intent(intent)

                return ToolResult(ok=True, data={"intent_name": intent_name, "intent_type": intent_type.value})

            elif action == "list_intents":
                intents = list(self.chatbot.intents.keys())
                return ToolResult(ok=True, data={"intents": intents})

            elif action == "register_response":
                intent_name = args.get("intent_name", "")
                response_text = args.get("response_text", "")

                if not intent_name or not response_text:
                    return ToolResult(ok=False, error="intent_name and response_text required")

                self.chatbot.register_response(intent_name, response_text)
                return ToolResult(ok=True, data={"registered": intent_name})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DialogueManagementTool(Tool):
    """Manage dialogue state and context."""

    name = "chatbot_dialogue"
    category = "chatbot"
    description = "Manage dialogue state and flow"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get_state", "reset_dialogue"], "description": "Dialogue action"}
        },
        "required": ["action"],
    }

    def __init__(self):
        self.chatbot = core.Chatbot()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "get_state":
                state = self.chatbot.dialogue_state.to_dict()
                return ToolResult(ok=True, data=state)

            elif action == "reset_dialogue":
                self.chatbot.reset()
                return ToolResult(ok=True, data={"status": "reset"})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ConversationTool(Tool):
    """Process messages and manage conversations."""

    name = "chatbot_conversation"
    category = "chatbot"
    description = "Process user messages and get responses"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["process_message", "get_history"],
                "description": "Conversation action",
            },
            "message": {"type": "string", "description": "User message to process"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.chatbot = core.Chatbot()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "process_message":
                message = args.get("message", "")
                if not message:
                    return ToolResult(ok=False, error="message required")

                response = await self.chatbot.process_message(message)
                return ToolResult(ok=True, data=response.to_dict())

            elif action == "get_history":
                history = self.chatbot.get_conversation_history()
                return ToolResult(ok=True, data={"conversation": history})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_chatbot_tools(registry):
    """Register all chatbot tools."""
    registry.register(IntentManagementTool())
    registry.register(DialogueManagementTool())
    registry.register(ConversationTool())
