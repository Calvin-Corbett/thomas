"""Reach the plugin rows on the Plugins page, which opens on ready-made sets with the long list folded away.

``thomas/server/web/settings.plugins-panel.js`` shows the sets first and keeps every plugin's row under a button, "Advanced:
choose each plugin yourself". A walk that presses or reads one plugin's row opens that first. The page decides what to show
once the plugins have been read, so this waits until it has, and presses the button only when the rows are still folded.
"""

from __future__ import annotations

from typing import Any

_SETTLED = """() => {
  const toggle = document.querySelector('#plugins .plugins-advanced-toggle');
  const row = document.querySelector('#plugins .plugin-row');
  return Boolean((toggle && !toggle.hidden) || (row && row.offsetParent !== null));
}"""


def open_the_plugin_list(page: Any, timeout: int = 60_000) -> None:
    """Make the plugin rows visible: wait for the page to settle, then open the Advanced section if it is closed."""
    page.wait_for_function(_SETTLED, timeout=timeout)
    toggle = page.locator("#plugins .plugins-advanced-toggle")
    if toggle.is_visible() and toggle.get_attribute("aria-expanded") != "true":
        toggle.click()
