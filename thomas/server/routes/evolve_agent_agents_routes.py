"""Where your saved Anthropic key is read from, for the runner that reaches Claude with it.

Thomas's loop runs Claude only with an Anthropic key. The key can sit in the model menu's key box, in the
``anthropic`` profile in thomas.toml, or under Settings > Anthropic Configuration;
:func:`saved_anthropic_key` reads all three, and :func:`install_saved_anthropic_key_reader` hands it to Build.
"""

from __future__ import annotations

import logging
import sqlite3

from aiohttp import web

from thomas.core.coding_agents import read_stored_anthropic_key_with
from thomas.server.app_keys import APP_CONFIG, APP_SECRETS

log = logging.getLogger(__name__)

#: The model profile whose saved key is Anthropic's. Only this one: another
#: profile on the anthropic provider may point at a different service, and its key
#: must not be sent to Anthropic.
ANTHROPIC_PROFILE = "anthropic"


def saved_anthropic_key(app: web.Application) -> str:
    """Your Anthropic key as the app saved it: the model menu's key box, the profile in
    thomas.toml, or Settings > Anthropic Configuration (the preferences store)."""
    secrets = app.get(APP_SECRETS)
    key = ""
    try:  # a store that cannot answer means no saved key; it must never fail a Build start
        key = str((secrets.get(ANTHROPIC_PROFILE) if secrets is not None else "") or "").strip()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        log.debug("the secret store could not be read for an Anthropic key", exc_info=True)
    config = app.get(APP_CONFIG)
    profile = getattr(config, "models", {}).get(ANTHROPIC_PROFILE) if config is not None else None
    key = key or str(getattr(profile, "api_key", "") or "").strip()
    if key:
        return key
    try:
        from thomas.preferences.store import PreferencesStore, get_db_path

        return str(PreferencesStore(get_db_path()).get_api_key_plain("default", ANTHROPIC_PROFILE) or "").strip()
    except (ImportError, OSError, RuntimeError, ValueError, sqlite3.Error):
        log.debug("the preferences store could not be read for an Anthropic key", exc_info=True)
        return ""


def install_saved_anthropic_key_reader(app: web.Application) -> None:
    """Let Thomas's loop reach Claude with a key saved in the app, not only one in the server's environment.

    The settings contract and the launch both ask for the key, so it is read from the same saved places.
    """
    read_stored_anthropic_key_with(lambda: saved_anthropic_key(app))
