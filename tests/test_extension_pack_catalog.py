"""The marketplace may not offer what it cannot install.

This file used to be *written by* ``scripts/generate_gap_assets.py``, the same
script that generated 528 ``pack-*`` directories — so it asserted that at least
480 of them existed. A generator producing both the artefacts and the test that
proves they exist can only ever pass.

Those packs were deleted on 2026-09-09. Measured before removing them:

- 528 directories, three files each, and exactly **two** distinct ``hooks.py``
  shapes once identifiers were normalised — one template stamped 480 times and
  another 48 times.
- Nothing ever loaded their code. ``extension_catalog_runtime`` checks that
  ``hooks.py`` exists and never imports it.
- None was installable. The real validator rejects them:
  *"Plugin 'pack-alerts-email' is not installable as a desktop plugin."*
- Yet ``classify_marketplace_row`` returned ``availability: installable`` and
  ``promotion_status: official_hosted`` for them, identical to the genuine
  ``paper-trading`` extension. The storefront advertised 480 items that failed
  the moment anyone chose one.

The last test below is the one that matters going forward. It closes the gap
between what the marketplace claims and what the installer accepts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

EXTENSIONS = Path(__file__).resolve().parents[1] / "extensions"


def _catalog() -> dict:
    return json.loads((EXTENSIONS / "catalog.json").read_text(encoding="utf-8"))


def test_the_generated_packs_do_not_come_back() -> None:
    """A deletion a merge can undo is not a deletion.

    Restoring a deleted tree is a thing this repository has done before, and the
    only thing that ever caught it was a test asserting the files MUST NOT
    exist. ``generate_extension_packs()`` was removed from the generator in the
    same change; this is the guard for the merge that tries to bring it back.
    """
    revived = sorted(p.name for p in EXTENSIONS.iterdir() if p.is_dir() and p.name.startswith("pack-"))
    assert revived == [], f"generated extension packs are back: {revived[:5]}"


def test_every_catalog_row_has_a_directory_and_the_required_fields() -> None:
    packs = _catalog()["packs"]
    assert packs, "the catalog must not be empty"

    seen: set[str] = set()
    for row in packs:
        pack_id = str(row["id"])
        assert pack_id not in seen, f"duplicate catalog id {pack_id}"
        seen.add(pack_id)

        directory = EXTENSIONS / pack_id
        assert directory.is_dir(), f"catalog lists {pack_id} but there is no directory"
        assert (directory / "manifest.json").exists()
        for key in ("id", "name", "version", "entrypoint", "capabilities"):
            assert key in row, f"{pack_id} is missing {key}"
        assert isinstance(row["capabilities"], list) and row["capabilities"]


def test_every_directory_is_in_the_catalog() -> None:
    """The other direction: 48 pack dirs were on disk that the catalog never listed."""
    on_disk = {p.name for p in EXTENSIONS.iterdir() if p.is_dir()}
    listed = {str(row["id"]) for row in _catalog()["packs"]}
    assert on_disk - listed == set(), f"extensions on disk that nothing indexes: {sorted(on_disk - listed)}"


def test_every_row_the_marketplace_calls_installable_can_actually_install() -> None:
    """The claim and the installer have to agree.

    ``classify_marketplace_row`` is what the marketplace route uses to label a
    row, and ``load_bundled_desktop_plugin_manifest`` is what the install path
    actually runs. For 480 rows those two disagreed completely.
    """
    from thomas.marketplace.surface_policy import classify_marketplace_row
    from thomas.server.desktop_plugins_manifest import load_bundled_desktop_plugin_manifest

    liars: list[str] = []
    for row in _catalog()["packs"]:
        pack_id = str(row["id"])
        verdict = classify_marketplace_row(row, installable_candidate=True)
        if verdict.get("availability") != "installable":
            continue
        try:
            load_bundled_desktop_plugin_manifest(pack_id)
        except (ValueError, FileNotFoundError, KeyError, TypeError) as exc:
            liars.append(f"{pack_id}: {type(exc).__name__}: {exc}")

    assert liars == [], "the marketplace offers rows the installer rejects:\n  " + "\n  ".join(liars)


@pytest.mark.parametrize(
    "kept",
    ["desktop-operator", "inkwell", "life-manager", "life-manager-foundation", "paper-trading"],
)
def test_the_real_extensions_survived(kept: str) -> None:
    """The five that carry actual code, named so a future cleanup cannot sweep them."""
    assert (EXTENSIONS / kept / "manifest.json").exists()


def _load_hooks(pack_dir: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"hc_{pack_dir.name.replace('-', '_')}", pack_dir / "hooks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_declared_healthcheck_is_an_implemented_healthcheck() -> None:
    """Declaring a capability you do not implement is the defect this repo just deleted.

    All 480 removed packs listed ``healthcheck`` in their manifest capabilities
    while their ``hooks.py`` defined only ``before_tool``/``after_tool``. That
    carried extension certification over its 95% bar without certifying
    anything. Any extension that claims the capability must actually answer.
    """
    for row in _catalog()["packs"]:
        pack_id = str(row["id"])
        if "healthcheck" not in (row.get("capabilities") or []):
            continue
        module = _load_hooks(EXTENSIONS / pack_id)
        healthcheck = getattr(module, "healthcheck", None)
        assert callable(healthcheck), f"{pack_id} declares healthcheck but does not define one"
        result = healthcheck()
        assert isinstance(result, dict) and "ok" in result, f"{pack_id} healthcheck returned {result!r}"
        assert result["ok"] is True, f"{pack_id} is unhealthy: {result}"


def test_a_healthcheck_can_actually_fail() -> None:
    """A check that can only pass is not a check.

    Breaks a real copy of each surface-backed extension and requires the
    healthcheck to notice. Without this the tests above would still pass on
    four functions that returned ``{"ok": True}`` unconditionally.
    """
    import shutil
    import tempfile

    surface_backed = [
        str(row["id"])
        for row in _catalog()["packs"]
        if "healthcheck" in (row.get("capabilities") or [])
        and (EXTENSIONS / str(row["id"]) / "web" / "index.html").is_file()
    ]
    assert surface_backed, "expected at least one surface-backed extension to break"

    with tempfile.TemporaryDirectory() as raw:
        for pack_id in surface_backed:
            broken = Path(raw) / pack_id
            shutil.copytree(EXTENSIONS / pack_id, broken)
            (broken / "web" / "index.html").unlink()

            result = _load_hooks(broken).healthcheck()
            assert result["ok"] is False, f"{pack_id} reported healthy with its surface deleted: {result}"
            assert "error" in result
