"""Tools for event platform operations."""

from typing import Any

from thomas.marketplace.event_platform import core
from thomas.tools.base import Tool, ToolResult


class TopicManagementTool(Tool):
    """Create and manage topics."""

    name = "event_topics"
    category = "event_platform"
    description = "Create and manage event topics"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_topic", "delete_topic", "list_topics", "topic_stats"],
                "description": "Topic action",
            },
            "topic": {"type": "string", "description": "Topic name"},
            "partitions": {"type": "integer", "description": "Number of partitions"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.broker = core.EventBroker()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            topic = args.get("topic", "")
            partitions = args.get("partitions", 1)

            if action == "create_topic":
                if not topic:
                    return ToolResult(ok=False, error="topic required")
                t = self.broker.create_topic(topic, partitions)
                return ToolResult(ok=True, data={"topic": topic, "partitions": partitions})

            elif action == "delete_topic":
                if not topic:
                    return ToolResult(ok=False, error="topic required")
                success = self.broker.delete_topic(topic)
                return ToolResult(ok=True, data={"deleted": success})

            elif action == "list_topics":
                topics = list(self.broker.topics.keys())
                return ToolResult(ok=True, data={"topics": topics, "count": len(topics)})

            elif action == "topic_stats":
                if not topic:
                    return ToolResult(ok=False, error="topic required")
                t = self.broker.get_topic(topic)
                if not t:
                    return ToolResult(ok=False, error=f"Topic {topic} not found")
                stats = t.get_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PublishConsumeTool(Tool):
    """Publish and consume events."""

    name = "event_messages"
    category = "event_platform"
    description = "Publish and consume events from topics"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["publish", "consume", "replay"], "description": "Message action"},
            "topic": {"type": "string", "description": "Topic name"},
            "key": {"type": "string", "description": "Event key"},
            "value": {"type": "object", "description": "Event value"},
            "partition": {"type": "integer", "description": "Partition number"},
            "start_offset": {"type": "integer", "description": "Starting offset"},
            "max_count": {"type": "integer", "description": "Maximum events to consume"},
        },
        "required": ["action", "topic"],
    }

    def __init__(self):
        self.broker = core.EventBroker()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            topic = args.get("topic", "")

            if action == "publish":
                key = args.get("key")
                value = args.get("value", {})
                event_id = self.broker.publish(topic, key, value)
                if not event_id:
                    return ToolResult(ok=False, error=f"Topic {topic} not found")
                return ToolResult(ok=True, data={"event_id": event_id, "topic": topic})

            elif action == "consume":
                partition = args.get("partition", 0)
                start_offset = args.get("start_offset", 0)
                max_count = args.get("max_count", 100)

                t = self.broker.get_topic(topic)
                if not t:
                    return ToolResult(ok=False, error=f"Topic {topic} not found")

                events = t.consume(partition, start_offset, max_count)
                return ToolResult(ok=True, data={"events": [e.to_dict() for e in events], "count": len(events)})

            elif action == "replay":
                from_offset = args.get("start_offset", 0)
                events = self.broker.replay_events(topic, from_offset)
                return ToolResult(ok=True, data={"events": [e.to_dict() for e in events], "count": len(events)})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_event_platform_tools(registry):
    """Register all event platform tools."""
    registry.register(TopicManagementTool())
    registry.register(PublishConsumeTool())
