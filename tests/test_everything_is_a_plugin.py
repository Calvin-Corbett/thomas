"""Everything Thomas is and runs belongs to the kernel or to exactly one plugin.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md section 7. You asked for a small kernel with
everything else as plugins. Selection runs this in every full check (``proof.selection.ALWAYS``), so a new file in a code
folder is claimed the day it lands, and "everything" stays true.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.plugins import carve

from thomas.core import plugin_manifest
from thomas.core.plugin_manifest import KERNEL, claims

ROOT = Path(__file__).resolve().parents[1]
FIX = "FIX: run `python -m scripts.plugins.carve`. If the file belongs elsewhere, add it to MAP in scripts/plugins/carve.py."


def _tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True, timeout=120).stdout
    return {p.decode("utf-8") for p in out.split(b"\0") if p}


def test_every_file_in_a_code_folder_is_the_kernels_or_one_plugins() -> None:
    manifests = plugin_manifest.load(ROOT)
    in_kernel = claims(KERNEL)
    code = [p for p in _tracked() if p.startswith(carve.CODE_ROOTS)]
    assert len(code) > 2000, "the code folders hold almost nothing: this test would hold nothing"

    unclaimed = sorted(p for p in code if not in_kernel(p) and plugin_manifest.owner(manifests, p) is None)

    assert unclaimed == [], f"{FIX}\n" + "\n".join(unclaimed)


def test_the_map_names_a_manifest_for_every_plugin_and_no_others() -> None:
    assert {m.name for m in plugin_manifest.load(ROOT)} == {plugin.name for plugin in carve.MAP}


def test_a_test_measured_to_need_more_than_its_plugin_is_claimed_by_none() -> None:
    listed = carve.integration_tests()
    assert listed <= _tracked(), f"listed but gone: {sorted(listed - _tracked())}"
    claimed = {path for manifest in plugin_manifest.load(ROOT) for path in listed if manifest.in_tests(path)}
    assert claimed == set(), f"{FIX}\n" + "\n".join(sorted(claimed))


def test_the_kernel_stays_small_and_imports_nothing_of_thomas_but_itself() -> None:
    kernel = sorted((ROOT / "thomas" / "core" / "kernel").glob("*.py"))
    assert kernel and sum(len(p.read_text(encoding="utf-8").splitlines()) for p in kernel) < 2000
    for path in kernel:
        for line in path.read_text(encoding="utf-8").splitlines():
            words = line.split()
            if words[:1] in (["import"], ["from"]) and words[1].startswith("thomas"):
                assert words[1].startswith("thomas.core.kernel"), f"{path.name}: {line.strip()}"
