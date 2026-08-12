"""A generated app that saves your work must still have it when you come back.

Every entry into a preview went through `__enter/<token>`, which sent
``Clear-Site-Data: "cache", "storage"``. The storage clear ran on every load, so
any deliverable using localStorage forgot everything the moment the panel was
reopened. 29 of 442 generated files use localStorage -- about one deliverable in
fifteen.

Measured, same origin throughout::

    navigate straight to the resolved preview URL, twice   kept, kept
    the same page through the redirect                     LOST

The clear was NOT pointless: the preview port is reused between grants, so it
stopped one deliverable reading keys another had left on the same origin. What
remains after dropping `"storage"` is exactly that risk -- a later preview
landing on a recycled ephemeral port could see the previous deliverable's keys.
Both are the owner's own generated apps on loopback.

`"cache"` stays. A stale build served after an edit is a correctness problem,
and nothing about persistence needs it gone.

This also stands as the record of a wrong turn: the CSP `sandbox` directive was
blamed first and removed, on a three-way comparison where the two passing cases
were navigated directly and the failing one went through the redirect. Two
variables, one conclusion. Removing the directive changed nothing and it was put
back -- see the note beside it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELIVERABLE = ROOT / "thomas" / "server" / "routes" / "deliverable_aiohttp.py"


def _code() -> str:
    """Source with comment lines dropped.

    The change is documented directly above itself and the note quotes the old
    header verbatim, so a scan that reads its own comment would pass with the
    fix reverted.
    """

    return "\n".join(
        line for line in DELIVERABLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_entering_a_preview_does_not_wipe_its_storage() -> None:
    code = _code()
    header = re.search(r'"Clear-Site-Data":\s*(\'[^\']*\'|"[^"]*")', code)
    assert header, "the Clear-Site-Data header is gone entirely; expected a cache-only clear"
    value = header.group(1)
    assert "storage" not in value, (
        "entering a preview clears site storage again, so every generated app "
        "that saves your work forgets it the moment the panel is reopened. "
        f"Got: {value}"
    )


def test_the_cache_clear_is_kept() -> None:
    """Dropping the whole header would trade one bug for another.

    Without the cache clear a stale build can be served after an edit, and the
    owner sees yesterday's app while the report describes today's.
    """

    code = _code()
    header = re.search(r'"Clear-Site-Data":\s*(\'[^\']*\'|"[^"]*")', code)
    assert header and "cache" in header.group(1), (
        "the cache clear was removed along with the storage clear; a stale "
        "deliverable can now be served after an edit"
    )


def test_the_sandbox_directive_was_put_back() -> None:
    """The wrong fix must stay reverted.

    Removing the CSP `sandbox` directive was tried on a confounded measurement,
    achieved nothing, and cost the call-site-independent containment backstop.
    If it disappears again it should be for a reason that survives a controlled
    test.
    """

    code = _code()
    joined = re.sub(r'"\s*\n\s*"', "", code)
    preview_csp = next(
        (m.group(0) for m in re.finditer(r'"[^"]*default-src \'self\' data: blob:[^"]*"', joined)),
        None,
    )
    assert preview_csp, "the artifact preview CSP is gone or no longer sets default-src"
    assert "sandbox" in preview_csp, (
        "the CSP `sandbox` directive is missing from the artifact preview policy. "
        "It was removed once to fix storage, did not fix storage, and was "
        "restored; the real cause was Clear-Site-Data on the __enter handler"
    )
