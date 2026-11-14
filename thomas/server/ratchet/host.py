"""Only the caged Thomas account may drive the ratchet or run candidate code, and only from Thomas's own source."""

from __future__ import annotations

import getpass
import os

from thomas.server import green_checkout
from thomas.server.ratchet.screen import cage_checks

AUTORUN_ENV = "THOMAS_RATCHET_AUTORUN"
ACCOUNT_ENV = "THOMAS_RATCHET_ACCOUNT"


def autorun_enabled() -> bool:
    return str(os.environ.get(AUTORUN_ENV, "1")).strip().lower() not in {"0", "false", "no", "off"}


def _no_checks_here() -> str:
    """Why a run cannot work in this install ("" when it can): a run checks each change as the promoter will."""
    try:
        cage_checks()
    except ImportError:
        return (
            "the ratchet runs only in the caged Thomas, from Thomas's own source, and this install has none of the "
            "checks a run needs, because a release leaves them out"
        )
    return ""


def host_refusal() -> str:
    """Why this process may not drive the ratchet ("" when it may)."""
    missing = _no_checks_here()
    if missing:
        return missing
    wanted = str(os.environ.get(ACCOUNT_ENV) or green_checkout.CAGE_ACCOUNT).strip().lower()
    here = getpass.getuser().strip().lower()
    if here == wanted:
        return ""
    return (
        f"the ratchet runs only in the caged Thomas (as {wanted}); this server runs as {here}, and a repair "
        "started here would run a candidate's old code under that account"
    )
