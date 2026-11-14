"""Where the server starts its engines, and how the aliveness setting still decides the first state of that plugin.

The aliveness sweep is a plugin you switch on the Plugins page, so the engine manager no longer starts it here. Before
that, ``THOMAS_ALIVENESS_ENABLED`` was the only way to run it, and it still starts the sweep: the first time a Thomas
with that setting starts and you have never chosen, the plugin is saved as on. From then on your choice wins, whatever the
setting says, because the setting is only where a Thomas with no choice begins.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from thomas.core.aliveness_setting import is_enabled as setting_is_on
from thomas.core.atomic_json import write_json_atomic
from thomas.core.config import resolve_thomas_data_dir

log = logging.getLogger(__name__)

PLUGIN = "aliveness"


def begin_on_if_never_chosen() -> bool:
    """Save the plugin as on, once, when you have no saved choice for it. True when it wrote one."""
    from thomas.server.runtime_plugins import read_choices

    path = Path(resolve_thomas_data_dir()) / "plugins" / "choices.json"
    choices, problem = read_choices(path)
    if problem or PLUGIN in choices:
        return False  # a damaged file is the Plugins page's to report, and it is not ours to replace
    try:
        write_json_atomic(path, {**choices, PLUGIN: {"enabled": True}})
    except OSError as exc:
        log.warning("The aliveness setting could not be saved as your first choice, so it starts off: %s", exc)
        return False
    return True


def start_engines() -> tuple[Any, dict[str, bool]]:
    """Start every engine except the aliveness sweep, and return the manager with what each one did."""
    from thomas.core.engine_manager import get_engine_manager

    manager = get_engine_manager()
    if setting_is_on():
        begin_on_if_never_chosen()
    return manager, manager.start_all(aliveness=False)
