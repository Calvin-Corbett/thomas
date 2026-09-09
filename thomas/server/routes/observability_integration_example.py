"""Example integration of observability event tracking into Thomas routes.

This file shows how to integrate the observability dashboard with existing
Thomas route handlers and the agent system.

Copy patterns from here to add event tracking throughout the codebase.
"""

from __future__ import annotations

from thomas.server.routes.observability import record_event, update_metrics


# Example 1: Track tool calls in a route handler
async def example_tool_call_handler(request):
    """Example of tracking a tool call event."""
    tool_name = request.query.get("tool")
    params = request.query.get("params", "{}")

    record_event(
        event_type="tool",
        source_agent="example_agent",
        message=f"Executing tool: {tool_name}",
        details={"tool": tool_name, "parameters": params, "timestamp": "2024-02-26T21:30:00Z"},
    )

    # ... execute tool ...

    return {"status": "success"}


# Example 2: Track LLM API calls
async def example_llm_request_handler(request):
    """Example of tracking an LLM request."""
    model = request.json.get("model")
    tokens_used = 1500

    record_event(
        event_type="llm",
        source_agent="chat_agent",
        message=f"LLM request to {model}",
        details={"model": model, "tokens_used": tokens_used, "tokens_input": 1000, "tokens_output": 500},
    )

    # ... make LLM call ...

    return {"tokens": tokens_used}


# Example 3: Track agent actions
async def example_agent_action(agent_name: str, action: str, details: dict):
    """Example of tracking agent actions."""
    record_event(event_type="agent", source_agent=agent_name, message=f"Agent action: {action}", details=details)


# Example 4: Track errors and exceptions
async def example_error_handler(exception: Exception, agent_name: str):
    """Example of tracking errors."""
    record_event(
        event_type="error",
        source_agent=agent_name,
        message=f"Error occurred: {str(exception)}",
        details={
            "error_type": type(exception).__name__,
            "traceback": "...",  # Add relevant traceback info
        },
    )


# Example 5: Track system metrics updates
def example_update_metrics(
    active_agents: int,
    queue_size: int,
    memory_mb: float,
    uptime_seconds: int,
    request_rate: float,
    error_rate: float,
):
    """Example of updating system metrics."""
    update_metrics(
        {
            "active_agents": active_agents,
            "tasks_queued": queue_size,
            "memory_usage": memory_mb,
            "uptime_seconds": uptime_seconds,
            "request_rate": request_rate,
            "error_rate": error_rate,
        }
    )


# Example 6: Integration in chat route
async def example_chat_handler_with_tracking(request):
    """Example of integrating tracking into a chat handler."""
    session_id = request.match_info.get("session_id")
    message = await request.json()

    # Track the incoming message
    record_event(
        event_type="agent",
        source_agent=f"chat_{session_id}",
        message="Processing chat message",
        details={"message_length": len(message.get("content", "")), "model": message.get("model", "unknown")},
    )

    # ... process message ...

    # Track successful completion
    record_event(
        event_type="agent",
        source_agent=f"chat_{session_id}",
        message="Chat message processed successfully",
        details={"response_tokens": 500},
    )

    return {"status": "success"}


# Example 7: Middleware integration for request tracking
class ObservabilityMiddleware:
    """Middleware to track all HTTP requests and responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, request, handler):
        # Track incoming request
        record_event(
            event_type="system",
            source_agent="http_middleware",
            message=f"HTTP {request.method} {request.path}",
            details={"method": request.method, "path": request.path, "query": str(request.query_string)},
        )

        try:
            response = await handler(request)
            # Request was successful
            return response
        except Exception as e:
            # Track the error
            record_event(
                event_type="error",
                source_agent="http_middleware",
                message=f"HTTP {request.method} {request.path} failed",
                details={"error": str(e), "type": type(e).__name__},
            )
            raise


# Integration points to consider:
# 1. Agent loop (agent.loop.py) - track task execution
# 2. Tool executor (tools executor) - track each tool call
# 3. LLM client calls - track tokens and model usage
# 4. Task ledger updates - track state transitions
# 5. Error handlers - track failures
# 6. Session management - track session lifecycle
# 7. Chat modes - track different chat interaction types
# 8. Autonomy engine - track autonomy level changes
# 9. Guardrails decisions - track approval/rejection events
# 10. Memory management - track memory operations


# Example: How to call from within Thomas agent loop
def integrate_with_agent_loop_example():
    """
    In thomas/agent/loop.py, add tracking like this:

    ```python
    from thomas.server.routes.observability import record_event

    async def run_agent_iteration(self):
        agent_name = self.agent.name

        record_event(
            event_type="agent",
            source_agent=agent_name,
            message="Starting agent iteration",
            details={"iteration": self.iteration_count}
        )

        try:
            # ... agent execution ...
            result = await self._execute_tools(tools)

            record_event(
                event_type="tool",
                source_agent=agent_name,
                message=f"Tools executed: {len(result)} results",
                details={"tool_results": result}
            )

        except Exception as e:
            record_event(
                event_type="error",
                source_agent=agent_name,
                message=f"Agent iteration failed: {str(e)}",
                details={"error": str(e)}
            )
            raise
    ```
    """
    pass


# Example: Event type conventions
EVENT_TYPE_CONVENTIONS = {
    "tool": "Tool execution - called when using tools",
    "llm": "LLM API calls - called when making model requests",
    "agent": "Agent actions - called for agent behaviors and state changes",
    "error": "Errors and exceptions - called when something fails",
    "system": "System events - general logging",
}

# Example: Source agent naming conventions
SOURCE_AGENT_NAMING = {
    "chat_<session_id>": "Chat route handler",
    "agent_<agent_id>": "Named agent instance",
    "tool_executor": "Tool execution subsystem",
    "llm_client": "LLM client",
    "http_middleware": "HTTP request middleware",
    "task_scheduler": "Task scheduling system",
}


__all__ = [
    "example_tool_call_handler",
    "example_llm_request_handler",
    "example_agent_action",
    "example_error_handler",
    "example_update_metrics",
    "example_chat_handler_with_tracking",
    "ObservabilityMiddleware",
    "EVENT_TYPE_CONVENTIONS",
    "SOURCE_AGENT_NAMING",
]
