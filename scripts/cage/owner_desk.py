"""The owner's desk: answers the server's approval requests, as you, in your session.

The server files a request (thomas/tools/owner_desk.py): a catalogue card kind,
its details and a content hash. This renders the card from the pinned catalogue
-- never from anything the server wrote -- shows the Windows sign-in with the
pairing code, and writes the answer where only you can write. Run by
scripts/cage/promoter_service.py on every pass.

The desk asks only to raise one of Thomas's own limits, the one request the
server makes (thomas/server/dial_elevation.py), and only when the prompt shows
exactly the raise it records. Anything else -- another card kind, a raise whose
words differ from the one recorded, a catalogue that fails its pin -- is
answered "no" without asking.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from thomas.tools import trusted_card

_ID_RE = re.compile(r"^[0-9a-f]{32}$|^[A-Za-z0-9_-]{1,64}$")


def _windows_sign_in(action: str, reason: str) -> bool:
    from thomas.tools.windows_auth import verified_sign_in

    return bool(verified_sign_in(action, reason))


def _answer(answers: Path, rid: str, record: dict[str, object]) -> None:
    answers.mkdir(parents=True, exist_ok=True)
    staging = answers / f".{rid}.tmp"
    staging.write_bytes(json.dumps(record).encode("utf-8"))
    os.replace(staging, answers / f"{rid}.json")


def _record_grant(answers: Path, content_hash: str) -> None:
    """Remember an approved raise beside the answers, so a restart of the caged
    server keeps it (thomas/server/dial_elevation.py reads it back). Only ever
    raises what is recorded; the server's request names the dial and value as
    "dial=value", and anything the ladder does not know is ignored."""
    from thomas.server import dial_elevation
    from thomas.tools.owner_desk import GRANTS_NAME

    dial, _, value = content_hash.partition("=")
    new = dial_elevation.rank(dial, value)
    if new is None:
        return
    path = answers / GRANTS_NAME
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    if not isinstance(current, dict):
        current = {}
    old = dial_elevation.rank(dial, current.get(dial))
    if old is not None and old >= new:
        return
    current[dial] = value
    answers.mkdir(parents=True, exist_ok=True)
    staging = answers / f".{GRANTS_NAME}.tmp"
    staging.write_bytes(json.dumps(current).encode("utf-8"))
    os.replace(staging, path)


def _shows_what_it_records(kind: str, details: dict[str, object], content_hash: str) -> bool:
    """The desk asks only to raise one of Thomas's own limits, and only when its prompt shows exactly the raise it
    records (_record_grant reads content_hash; the prompt shows details)."""
    if kind != "raise_dial":
        return False
    from thomas.server import dial_elevation

    dial, _, value = content_hash.partition("=")
    label = dial_elevation._LABELS.get(dial)
    shown = {str(k): str(v) for k, v in details.items()}
    return (
        label is not None and dial_elevation.rank(dial, value) is not None and shown == {"dial": label, "value": value}
    )


def serve_once(root: Path, *, ask: Callable[[str, str], bool] | None = None, pin_root: Path | None = None) -> int:
    """Answer the oldest waiting request. Returns 1 if one was handled, else 0."""
    base = Path(root) / "desk"
    requests = base / "requests"
    waiting = sorted(requests.glob("*.json"), key=lambda p: p.stat().st_mtime) if requests.is_dir() else []
    if not waiting:
        return 0
    path = waiting[0]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    rid = str(data.get("id") or "") if isinstance(data, dict) else ""
    if rid != path.stem or not _ID_RE.match(rid):
        path.unlink(missing_ok=True)  # not a request anyone can be answered for
        return 1
    kind = str(data.get("kind") or "")
    details = data.get("details")
    content_hash = str(data.get("content_hash") or "")
    approved, code = False, ""
    if (
        trusted_card.catalogue_status(pin_root=pin_root) == "ok"
        and isinstance(details, dict)
        and _shows_what_it_records(kind, details, content_hash)
    ):
        catalogue = trusted_card.load_catalogue()
        try:
            title, body = catalogue.render(kind, details)
        except (KeyError, ValueError):
            title = body = ""
        if title:
            code = catalogue.pairing_code(kind, details, content_hash, rid)
            card = trusted_card.TrustedCard(
                kind=kind,
                details={str(k): str(v) for k, v in details.items()},
                content_hash=content_hash,
                nonce=rid,
                code=code,
                title=title,
                body=body,
            )
            approved = bool((ask or _windows_sign_in)(*card.dialog()))
    if approved and kind == "raise_dial":
        _record_grant(base / "answers", content_hash)
    _answer(
        base / "answers",
        rid,
        {
            "id": rid,
            "kind": kind,
            "content_hash": content_hash,
            "approved": approved,
            "pairing_code": code,
            "answered_at": time.time(),
        },
    )
    path.unlink(missing_ok=True)
    return 1


__all__ = ["serve_once"]
