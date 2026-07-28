"""A resource the harness refused to fetch is not a defect of the page.

The smoke browser runs with external name resolution mapped away on purpose, so
any page loading a library from a CDN could never pass. `blocktown-84.html`
loads three.js from jsdelivr: after Thomas repaired its real syntax error the
page booted with `errors: []`, and the build still failed — on a script the
harness had itself declined to fetch.

Saying "your game is broken" about a game that works is the same error as
passing a broken one, pointed the other way. Local resource failures still fail:
those are ours, and a missing local script is exactly what this exists to catch.
"""

from __future__ import annotations

from thomas.forge.anvil.web_artifact_smoke import _is_external_reference


def test_a_cdn_script_is_recognised_as_external() -> None:
    assert _is_external_reference("SCRIPT: https://cdn.jsdelivr.net/npm/three@0.159.0/build/three.min.js")


def test_the_harnesss_own_origin_is_not_external() -> None:
    assert not _is_external_reference("SCRIPT: http://127.0.0.1:8899/app.js")
    assert not _is_external_reference("LINK: http://localhost:5173/style.css")


def test_a_relative_local_asset_is_not_external() -> None:
    """A missing local file has no scheme and must still fail the build."""
    assert not _is_external_reference("SCRIPT: renderer.js")
    assert not _is_external_reference("IMG: assets/sprite.png")


def test_a_port_does_not_confuse_the_host_check() -> None:
    assert not _is_external_reference("SCRIPT: http://127.0.0.1:53421/game.js")
    assert _is_external_reference("SCRIPT: https://example.com:8443/lib.js")


def test_an_unparseable_line_is_treated_as_local() -> None:
    """Unknown means it still counts against the build: a resource failure we
    cannot attribute is not something to wave through."""
    assert not _is_external_reference("load failed")
