from __future__ import annotations

import json
from pathlib import Path

from thomas.plugins.certification import build_plugin_update_plan_from_state, certify_extension_catalog


def _write_pack(root: Path, *, pack_id: str, manifest_version: str, catalog_version: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    pack_dir = root / pack_id
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "hooks.py").write_text("def register(registry):\n    return None\n", encoding="utf-8")
    (pack_dir / "README.md").write_text(f"# {pack_id}\n", encoding="utf-8")
    (pack_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": pack_id,
                "name": f"{pack_id} extension",
                "version": manifest_version,
                "entrypoint": "hooks.py",
                "capabilities": ["healthcheck"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "catalog.json").write_text(
        json.dumps(
            {
                "packs": [
                    {
                        "id": pack_id,
                        "name": f"{pack_id} extension",
                        "version": catalog_version,
                        "entrypoint": "hooks.py",
                        "capabilities": ["healthcheck"],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return pack_dir


def test_certify_extension_catalog_reports_expected_shape() -> None:
    """Shape and the one real invariant - deliberately not the pass rate.

    This asserted ``ok is True`` and ``total >= 480`` until 2026-09-09. Both
    held only because 528 generated packs existed, and every one of them
    DECLARED the required ``healthcheck`` capability while its ``hooks.py``
    defined nothing but ``before_tool``/``after_tool``. They lifted the pass
    rate over the 95% bar without implementing the thing being certified.

    With the packs deleted the rate is measured rather than padded: 1 of the 5
    real extensions (``paper-trading``, which does implement ``def
    healthcheck()``). Whether the other four should declare and implement one
    is an owner decision, so this asserts what it is named for instead of a
    threshold it can only meet by re-adding filler.
    """
    payload = certify_extension_catalog()
    assert {"ok", "summary", "coverage", "uncertified"} <= set(payload)
    # Re-asserted 2026-09-09 once the four remaining extensions gained real
    # healthchecks. It now means what it always claimed to: 5 of 5 certified
    # because each implements the capability, not because 480 stubs declared it.
    assert payload["ok"] is True

    summary = payload["summary"]
    assert int(summary["catalog_invalid"]) == 0
    assert int(summary["total"]) == int(summary["certified"]) + int(summary["uncertified"])
    assert int(summary["total"]) >= 1


def test_build_plugin_update_plan_from_state_uses_catalog_versions(tmp_path: Path) -> None:
    catalog_root = tmp_path / "extensions"
    pack_dir = _write_pack(
        catalog_root,
        pack_id="pack-test-updatable",
        manifest_version="1.0.0",
        catalog_version="1.2.0",
    )
    payload = build_plugin_update_plan_from_state(
        [{"name": "pack-test-updatable", "path": str(pack_dir)}],
        catalog_root=catalog_root,
    )
    assert payload["ok"] is True
    assert int(payload["summary"]["total"]) == 1
    assert int(payload["summary"]["update"]) == 1
    action = payload["actions"][0]
    assert action["id"] == "pack-test-updatable"
    assert action["latest_version"] == "1.2.0"


def test_certification_rejects_a_declared_but_unimplemented_capability(tmp_path: Path) -> None:
    """The 480-pack lie, reproduced and refused.

    Every deleted pack listed ``healthcheck`` in its manifest capabilities while
    its ``hooks.py`` defined only ``before_tool``/``after_tool``. Certification
    compared the required capability against that declared list and nothing
    else, so all 480 certified and carried the 95% pass rate over its bar. This
    builds a pack of exactly that shape and requires certification to refuse it.
    """
    import shutil

    root = tmp_path / "extensions"
    shutil.copytree(Path(__file__).resolve().parents[1] / "extensions", root)

    liar = root / "pack-liar"
    liar.mkdir()
    manifest = {
        "id": "pack-liar",
        "name": "Liar",
        "version": "1.0.0",
        "entrypoint": "hooks.py",
        "capabilities": ["healthcheck"],
        "description": "declares healthcheck, implements nothing",
    }
    (liar / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (liar / "hooks.py").write_text("def before_tool(payload):\n    return dict(payload or {})\n", encoding="utf-8")
    (liar / "README.md").write_text("liar\n", encoding="utf-8")

    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    catalog["packs"].append(manifest)
    (root / "catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    payload = certify_extension_catalog(root=root)

    assert payload["ok"] is False
    uncertified_ids = [row["id"] for row in payload["uncertified"]]
    assert uncertified_ids == ["pack-liar"]
    row = payload["uncertified"][0]
    assert row["unimplemented_capabilities"] == ["healthcheck"]
    assert any("declared but not implemented" in r for r in row["reasons"])


def test_certification_reports_what_it_actually_verified(tmp_path: Path) -> None:
    """A summary must not imply more checking than happened.

    ``verified_by_execution`` counts packs whose capability was confirmed by
    running it; ``declared_only`` counts those taken on faith because no
    verifier exists for that capability yet. Without the split, a future
    capability with no verifier would silently inflate the pass rate the same
    way the packs did.
    """
    payload = certify_extension_catalog()
    summary = payload["summary"]

    assert summary["verified_by_execution"] == summary["total"]
    assert summary["declared_only"] == 0
    for row in payload["certified_sample"]:
        assert row["verified_capabilities"] == ["healthcheck"]
