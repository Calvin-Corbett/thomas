"""The secret canary tooling stays out of public releases.

thomas/security/secret_canaries.py and tests/test_secret_canaries.py are private security tooling. A public
release is built by scripts/forge/publish/snapshot.py, which leaves out every path that
docs/repo_hygiene_baseline.json lists under publish_strip_prefixes. These tests read the real baseline, so
they fail if either path is dropped from it.

The files are kept out by the strip list, never by a THOMAS_PRIVATE marker line: the pre-push publish preflight
(scripts/forge/publish/preflight.py) refuses every tracked file that carries one, so a marker would stop every
push of the development branch.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import scripts.forge.publish.private_markers as private_markers
import scripts.forge.publish.snapshot as snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE = REPO_ROOT / "docs" / "repo_hygiene_baseline.json"
CANARY_FILES = ("thomas/security/secret_canaries.py", "tests/test_secret_canaries.py")
PUBLIC_NEIGHBOURS = ("thomas/security/__init__.py", "tests/test_private_markers.py")


def test_the_publish_filter_drops_both_canary_files_and_keeps_their_neighbours() -> None:
    kept = snapshot._filter_publish_paths(REPO_ROOT, [*CANARY_FILES, *PUBLIC_NEIGHBOURS], respect_repo_hygiene=True)

    assert kept == sorted(PUBLIC_NEIGHBOURS)


def test_a_publish_snapshot_leaves_both_canary_files_out(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    for rel in (*CANARY_FILES, *PUBLIC_NEIGHBOURS):
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_text(f"# {rel}\n", encoding="utf-8")
    (source / "docs").mkdir()
    shutil.copyfile(BASELINE, source / "docs" / "repo_hygiene_baseline.json")
    listed = [*CANARY_FILES, *PUBLIC_NEIGHBOURS, "docs/repo_hygiene_baseline.json"]
    monkeypatch.setattr(snapshot, "_list_git_paths", lambda repo_root, *, include_untracked: list(listed))
    monkeypatch.setattr(snapshot, "_current_origin", lambda repo_root: "")
    monkeypatch.setattr(snapshot, "_init_snapshot_repo", lambda snapshot_root, *, origin_url: None)
    monkeypatch.setattr(snapshot, "_run_preflight", lambda snapshot_root, *, deep: {"ok": True})
    out = tmp_path / "snapshot"

    assert snapshot.run(["--repo-root", str(source), "--output-root", str(out), "--json"]) == 0

    for rel in PUBLIC_NEIGHBOURS:
        assert (out / rel).is_file(), f"{rel} should be published"
    for rel in CANARY_FILES:
        assert not (out / rel).exists(), f"{rel} reached the public snapshot"


def test_neither_canary_file_carries_a_private_marker_line() -> None:
    for rel in CANARY_FILES:
        assert not private_markers.path_has_private_marker(REPO_ROOT, rel), rel
