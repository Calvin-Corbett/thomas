"""Static assets carrying a content fingerprint are cached, even in development.

Measured on the owner's running server (2026-09-08, port 8899): every asset under
``/static/`` was served ``Cache-Control: no-store`` because the middleware only
granted caching when ``is_production`` was true. chat.html references 30 scripts
totalling roughly 1.1MB, and the tab shell gives every Chat/Build/Work tab its own
chat.html document -- so opening a tab re-downloaded and re-parsed the whole bundle,
and so did every reload.

Nothing required that. Each asset URL already carries ``?v=<hash of file content>``
(observed: ``chat_boot.js?v=352d21d3d9c1``, a different hash per file), so the URL
changes whenever the file changes. The server already emits ETag and Last-Modified
and already answers a conditional GET with ``304, 0 bytes``. The development branch
was defending freshness that the fingerprint had already guaranteed, and paying for
it on every tab.

The fix keeps production behaviour identical and, in development:
  - a fingerprinted asset is cached immutably -- an edit changes the hash, so the
    browser is forced to fetch the new file and edits still appear on reload;
  - an asset requested WITHOUT a fingerprint is ``no-cache``: the browser stores it
    but revalidates every time, so it gets a 0-byte 304 when unchanged and picks up
    an edit immediately.

Neither branch can serve a stale file, which is the property ``no-store`` was there
to protect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.server.app_middleware_handlers import resolve_ui_cache_control


@pytest.mark.parametrize("path", ["/", "/mission", "/settings", "/companion"])
def test_dynamic_pages_are_still_never_stored(path: str) -> None:
    """The HTML documents are rebuilt per request and must not be cached."""
    assert resolve_ui_cache_control(path, is_production=False, fingerprinted=False) == "no-store"
    assert resolve_ui_cache_control(path, is_production=True, fingerprinted=False) == "no-store"


def test_a_fingerprinted_asset_is_cached_in_development() -> None:
    """The regression this file exists for: ``?v=<content hash>`` makes caching safe.

    Serving no-store here is what made every new tab re-download and re-parse the
    whole 1.1MB script bundle.
    """
    header = resolve_ui_cache_control("/static/js/chat_boot.js", is_production=False, fingerprinted=True)
    assert "no-store" not in header
    assert "immutable" in header
    assert "max-age=31536000" in header


def test_an_unfingerprinted_asset_revalidates_instead_of_refetching() -> None:
    """Without a fingerprint the browser must ask -- but it may still keep the bytes.

    ``no-cache`` stores the response and revalidates on every use, so an unchanged
    file costs a 304 with an empty body instead of a full re-download, and an edited
    file is picked up on the very next request.
    """
    header = resolve_ui_cache_control("/static/js/chat_boot.js", is_production=False, fingerprinted=False)
    assert header == "no-cache"
    assert "no-store" not in header


def test_production_asset_caching_is_unchanged() -> None:
    for fingerprinted in (True, False):
        header = resolve_ui_cache_control("/static/js/chat_boot.js", is_production=True, fingerprinted=fingerprinted)
        assert header == "public, max-age=31536000, immutable"


def test_unrelated_paths_are_left_alone() -> None:
    """The middleware must not start dictating cache policy for API routes."""
    for path in ("/api/health", "/api/v2/chat", "/favicon.ico"):
        assert resolve_ui_cache_control(path, is_production=False, fingerprinted=False) is None


def test_no_development_branch_can_forbid_storing_a_fingerprinted_asset() -> None:
    """Guards the property directly, so the dev branch cannot regress to no-store."""
    for is_production in (True, False):
        header = resolve_ui_cache_control("/static/js/anything.js", is_production=is_production, fingerprinted=True)
        assert header is not None
        assert "no-store" not in header


MIDDLEWARE = Path(__file__).resolve().parents[1] / "thomas" / "server" / "app_middleware_handlers.py"


def test_asset_urls_change_when_any_frontend_file_changes() -> None:
    """The invariant that makes a one-year cache safe.

    The classic page does not stamp per file: its script tags carry the page build
    fingerprint, and app_runtime_loader.js reuses its own tag's ?v= for all 98 files
    under js/runtime/. (The chat page does stamp each file with a hash of its own bytes;
    see test_each_chat_page_file_has_its_own_cache_version.py.) Caching those for a year is only safe
    because _web_build_fingerprint hashes EVERY js/**.js and css/**.css by
    mtime+size, so editing any frontend file changes every asset URL at once.

    Narrowing that walk to a few named files would silently make every cached asset
    stale for a year -- which is the bug the walk was widened to fix: "a fix to any
    other runtime/NNN_*.js module left the ?v= UNCHANGED and browsers kept serving
    the cached, pre-fix frontend". This test fails if anyone narrows it again.
    """
    source = MIDDLEWARE.read_text(encoding="utf-8")
    walk = source[source.index("def _web_build_fingerprint(") :]
    walk = walk[: walk.index("_fingerprint_cache[relative_paths]")]
    assert 'for sub, pattern in (("js", "*.js"), ("css", "*.css")):' in walk, (
        "the fingerprint no longer covers all js and css; immutable caching would go stale"
    )
    assert "rglob(pattern)" in walk, "the walk must recurse into js/runtime/"
    assert "st_mtime_ns" in walk and "st_size" in walk, "an edit must change the stamp"
