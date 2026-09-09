"""REPL UI state machine for tracking overlay/popup transitions."""

from __future__ import annotations

from enum import Enum


class ReplUiState(str, Enum):
    IDLE = "idle"
    SLASH_POPUP = "slash_popup"
    PICKER = "picker"
    THINKING = "thinking"
    STREAMING = "streaming"


# Valid transitions: source -> set of allowed targets.
_VALID_TRANSITIONS: dict[ReplUiState, set[ReplUiState]] = {
    ReplUiState.IDLE: {ReplUiState.SLASH_POPUP, ReplUiState.PICKER, ReplUiState.THINKING, ReplUiState.STREAMING},
    ReplUiState.SLASH_POPUP: {ReplUiState.IDLE, ReplUiState.PICKER},
    ReplUiState.PICKER: {ReplUiState.IDLE, ReplUiState.SLASH_POPUP},
    ReplUiState.THINKING: {ReplUiState.IDLE, ReplUiState.STREAMING},
    ReplUiState.STREAMING: {ReplUiState.IDLE, ReplUiState.THINKING},
}


def is_valid_ui_transition(source: ReplUiState, target: ReplUiState) -> bool:
    """Return True if *source* -> *target* is a permitted UI state change."""
    if source == target:
        return True
    return target in _VALID_TRANSITIONS.get(source, set())
