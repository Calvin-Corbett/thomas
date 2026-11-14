"""Click on the older full page when the easy-setup window may open over it at any moment.

The window opens once the page has read the setup state from the server, which can be after the page looks ready. A
walk that checks for it once and then clicks loses the click to its backdrop whenever it opens in between, and waits out
the click's whole timeout. So a click that does not land is tried again after closing the window, and only a click that
fails three times in a row fails the walk.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

TRIES = 3
WAIT_MS = 8000


def close_easy_setup(page: Any) -> None:
    """Close the easy-setup window if it is showing."""
    if page.locator("#easySetupDismissBtn").is_visible():
        page.locator("#easySetupDismissBtn").click()


def click_past_easy_setup(page: Any, target: Callable[[], Any]) -> None:
    """Click ``target()`` (a locator, made fresh each try), closing the easy-setup window first and again after a miss."""
    from playwright.sync_api import TimeoutError as ClickMissed

    for attempt in range(TRIES):
        close_easy_setup(page)
        try:
            target().click(timeout=WAIT_MS)
            return
        except ClickMissed:
            if attempt == TRIES - 1:
                raise
