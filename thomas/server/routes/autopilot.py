"""
Public surface for chat-triggered autopilot auto-start.

This module re-exports :func:`maybe_auto_start_autopilot_from_chat` from
:mod:`thomas.server.routes.chat_helpers` so that callers can import from
``thomas.server.routes.autopilot`` — the path
:mod:`thomas.server.routes.chat_request_setup` uses.

Without this shim, the import in ``chat_request_setup.py`` raises
``ModuleNotFoundError`` and is silently swallowed by ``contextlib.suppress``,
which means the autopilot intent detector (24/7, continuous, monitor, etc.)
never fires on chat traffic — the exact failure mode caught by
``tests/test_server_mission_control.py::test_chat_prompt_auto_starts_autopilot_objective``.
"""

from __future__ import annotations

from thomas.server.routes.chat_helpers import maybe_auto_start_autopilot_from_chat

__all__ = ["maybe_auto_start_autopilot_from_chat"]
