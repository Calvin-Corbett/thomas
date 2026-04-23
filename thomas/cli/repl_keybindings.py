"""Configurable keybinding support for the Thomas REPL.

Reads keybindings from thomas.toml [repl.keybindings] and applies them to a
prompt_toolkit KeyBindings registry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class KeybindingSpec:
    """A single keybinding specification."""

    action: str
    keys: list[str] = field(default_factory=list)


# Default keybindings that are always available.
_DEFAULTS: list[dict[str, Any]] = [
    {"action": "newline", "keys": ["c-j"]},
    {"action": "exit", "keys": ["c-d"]},
    {"action": "clear_screen", "keys": ["c-l"]},
]


def load_keybindings(config: Any) -> list[KeybindingSpec]:
    """Load keybinding specs from *config*.

    Looks at ``config.repl.keybindings`` if available, otherwise returns
    defaults.
    """
    specs: list[KeybindingSpec] = []

    raw: list[dict[str, Any]] = _DEFAULTS
    try:
        repl_cfg = getattr(config, "repl", None)
        if repl_cfg and hasattr(repl_cfg, "keybindings"):
            custom = repl_cfg.keybindings
            if isinstance(custom, list) and custom:
                raw = custom
    except Exception:
        pass

    for entry in raw:
        action = str(entry.get("action", "")).strip()
        keys = entry.get("keys", [])
        if not action or not keys:
            continue
        if isinstance(keys, str):
            keys = [keys]
        specs.append(KeybindingSpec(action=action, keys=list(keys)))

    return specs


def apply_keybindings(bindings: Any, specs: list[KeybindingSpec], repl: Any) -> None:
    """Apply *specs* to a prompt_toolkit *bindings* registry.

    Supports actions: ``newline``, ``exit``, ``clear_screen``.
    """
    for spec in specs:
        if spec.action == "newline":
            for key in spec.keys:
                try:

                    @bindings.add(key)
                    def _newline(event: Any, _k: str = key) -> None:
                        event.current_buffer.insert_text("\n")

                except Exception as exc:
                    log.debug("Failed to bind %s for newline: %s", key, exc)

        elif spec.action == "exit":
            for key in spec.keys:
                try:

                    @bindings.add(key)
                    def _exit(event: Any, _k: str = key) -> None:
                        event.app.exit(exception=EOFError)

                except Exception as exc:
                    log.debug("Failed to bind %s for exit: %s", key, exc)

        elif spec.action == "clear_screen":
            for key in spec.keys:
                try:

                    @bindings.add(key)
                    def _clear(event: Any, _k: str = key) -> None:
                        event.app.renderer.clear()

                except Exception as exc:
                    log.debug("Failed to bind %s for clear_screen: %s", key, exc)
