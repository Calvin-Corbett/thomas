"""Every carved plugin stays inside its fence (spec 2026-10-29 section 2).

Reads only the plugin's own files and git's list of tracked paths, so it runs the same in a slim proof copy (where the
plugin's files are always present and git still lists every path) as in a full checkout. A slim copy holds one manifest,
so there this checks that one plugin; in a full checkout it checks them all.
"""

from __future__ import annotations

import subprocess
from functools import cache
from pathlib import Path

from thomas.core import plugin_fence, plugin_manifest, plugin_proof

ROOT = Path(__file__).resolve().parents[1]


@cache
def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True, timeout=120).stdout
    return {p.decode("utf-8") for p in out.split(b"\0") if p}


def test_every_plugin_imports_only_the_kernel_its_code_and_its_needs() -> None:
    tracked = _tracked()
    problems = []
    for manifest in plugin_manifest.load(ROOT):
        own = [p for p in tracked if p.endswith(".py") and manifest.in_code(p) and (ROOT / p).is_file()]
        sources = {p: _read(p) for p in own}
        problems += [f"{manifest.name}: {v}" for v in plugin_fence.violations(manifest, sources, tracked)]
    assert problems == [], "\n".join(problems)


def test_every_plugins_tests_reach_no_further_into_thomas_than_its_code() -> None:
    tracked = _tracked()
    graph = plugin_proof.ImportGraph(tracked, _read)
    problems = []
    for manifest in plugin_manifest.load(ROOT):
        found = plugin_proof.strays(manifest, tracked, _read, graph)
        problems += [f"{manifest.name}: {test} pulls in {path}" for path, test in found.items()]
    assert problems == [], "\n".join(problems)


def test_no_two_plugins_claim_one_tracked_path() -> None:
    manifests = plugin_manifest.load(ROOT)
    if not manifests:
        return
    for path in sorted(_tracked()):
        plugin_manifest.owner(manifests, path)  # raises ManifestError naming both plugins
