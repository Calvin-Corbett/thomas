"""Interactive picker / completion helpers for the Thomas REPL overlay prompts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


@dataclass
class PickerOption:
    """A single option presented in an overlay picker."""

    value: str
    label: str
    description: str = ""
    is_current: bool = False


class PickerCompleter(Completer):
    """Prompt-toolkit completer that yields ``PickerOption`` entries."""

    def __init__(self, options: Sequence[PickerOption], *, match_middle: bool = False) -> None:
        self._options = list(options)
        self._match_middle = match_middle

    def get_completions(self, document: Document, complete_event: Any) -> Any:
        text = (document.text_before_cursor or "").strip().lower()
        for opt in self._options:
            label_lower = opt.label.lower()
            if not text or label_lower.startswith(text) or (self._match_middle and text in label_lower):
                display_meta = opt.description
                if opt.is_current:
                    display_meta = f"{display_meta} (current)" if display_meta else "(current)"
                yield Completion(
                    opt.value,
                    start_position=-len(document.text_before_cursor),
                    display=opt.label,
                    display_meta=display_meta,
                )


def picker_toolbar_hint(total: int, visible: int) -> str:
    """Return a toolbar hint string for a picker overlay."""
    if total > visible:
        return f"up/down navigate · Tab accept · {total} items (scroll for more)"
    return f"up/down navigate · Tab accept · {total} items"


def resolve_picker_selection(typed: str, options: Sequence[PickerOption]) -> str:
    """Resolve *typed* text against *options*, returning the best match value."""
    if not typed:
        return ""
    typed_lower = typed.strip().lower()
    # Exact match on value
    for opt in options:
        if opt.value.lower() == typed_lower:
            return opt.value
    # Exact match on label
    for opt in options:
        if opt.label.lower() == typed_lower:
            return opt.value
    # Prefix match on label
    for opt in options:
        if opt.label.lower().startswith(typed_lower):
            return opt.value
    return typed
