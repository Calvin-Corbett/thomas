"""Code outside a carved plugin touches only the modules its manifest's ``door`` names.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md section 2a. A check that runs only a
plugin's tests cannot see a break in the code that depends on it, so everything that depends on it must have a name
those tests can pin. Selection runs this in every full check (``proof.selection.ALWAYS``), whatever changed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from thomas.core import plugin_fence, plugin_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_nothing_reaches_past_a_plugins_door() -> None:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT, timeout=30, check=True)
    tracked = set(out.stdout.splitlines())
    sources = {
        rel: (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for rel in sorted(tracked)
        if rel.endswith(".py") and not rel.startswith("tests/") and (ROOT / rel).is_file()
    }
    manifests = plugin_manifest.load(ROOT)
    assert any(m.door for m in manifests), "no plugin names a door, so this test would hold nothing"

    problems = [
        f"{manifest.name}: {reach}\n"
        f"  FIX: use what {manifest.source} lists under door. Whatever else is needed goes through the package's own "
        "names, so the plugin's tests can stand for it alone."
        for manifest in manifests
        for reach in plugin_fence.outsiders(manifest, sources, tracked)
    ]
    assert problems == [], "\n".join(problems)
