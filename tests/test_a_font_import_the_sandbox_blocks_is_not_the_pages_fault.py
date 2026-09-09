"""A stylesheet whose remote ``@import`` the offline sandbox blocks is not broken (2026-09-05).

Two builds in a row lost fix passes to this. The Mario Kart page's ``styles.css``
began with ``@import url('https://fonts.googleapis.com/...')``; the smoke's CSP
blocked that fetch, Chromium fired the ``error`` event on the ``<link>`` element,
and the receipt read ``LINK: http://thomas-smoke.invalid/styles.css`` -- the local
file, which had loaded fine. ``_is_external_reference`` excuses CDN failures, but
it never saw a CDN: it saw the sheet that did the importing. The build failed on a
page that works, the fix pass was told a local stylesheet failed, and the
Minecraft run before it had already learnt the same lesson the hard way ("remote
font imports can block module startup").

The receipt must name what was actually blocked. A stylesheet that imports a
LOCAL sheet which is missing is still the page's fault and still fails.
"""

from __future__ import annotations

import pytest

from thomas.forge.anvil import web_artifact_smoke as smoke

pytestmark = pytest.mark.skipif(smoke._browser_executable() is None, reason="Chrome or Edge is not installed")

_PAGE = (
    "<!doctype html><html><head><title>Turbo</title><link rel='stylesheet' href='styles.css'></head>"
    "<body><h1>Turbo Trails</h1><button id='go'>Start</button>"
    "<script>go.onclick=()=>{go.textContent='Racing';};</script></body></html>"
)


def test_a_blocked_remote_font_import_does_not_fail_the_page(tmp_path) -> None:
    (tmp_path / "index.html").write_text(_PAGE, encoding="utf-8")
    (tmp_path / "styles.css").write_text(
        "@import url('https://fonts.googleapis.com/css2?family=Nunito&display=swap');\n"
        "body{font-family:Nunito,sans-serif;background:#123}\n",
        encoding="utf-8",
    )

    result = smoke.smoke_html_artifacts(tmp_path, ["index.html"], timeout=20)

    assert result.attempted is True
    assert result.ok is True, result.summary
    receipt = result.receipts[0]
    # The receipt says what was blocked, not that the local sheet failed.
    assert any("fonts.googleapis.com" in str(v) for v in receipt.get("resource_errors") or []), receipt
    assert not any(str(v).startswith("LINK: http://thomas-smoke.invalid/styles.css") for v in receipt["resource_errors"]), receipt
    assert any("(imported by http://thomas-smoke.invalid/styles.css)" in str(v) for v in receipt["resource_errors"]), receipt


def test_a_missing_local_import_is_still_the_pages_fault(tmp_path) -> None:
    (tmp_path / "index.html").write_text(_PAGE, encoding="utf-8")
    (tmp_path / "styles.css").write_text("@import url('theme.css');\nbody{background:#123}\n", encoding="utf-8")

    result = smoke.smoke_html_artifacts(tmp_path, ["index.html"], timeout=20)

    assert result.attempted is True
    assert result.ok is False, result.summary
    assert "theme.css" in result.summary
