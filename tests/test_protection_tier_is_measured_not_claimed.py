"""The reported protection tier must come from an attempted write, not a setting.

Written 2026-09-19, the day every safety layer in this repo was found reporting a
protection it did not have: gates printing PASS without running, a verification
record claiming a pass from `python -c print(123)`, `os_protect.py` at
`0 locked, 94 open`, and a frontend gate answering "clean" when it could not start
the compiler. The tier reporter is the one place that must not join them.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from thomas.core import protection_tier as pt


def _repo(tmp_path: Path) -> Path:
    """A miniature repo carrying the whole enforcement surface."""
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    (tmp_path / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (tmp_path / "agent_safety.toml").write_text("[protected_files]\n", encoding="utf-8")
    (tmp_path / "scripts" / "forge" / "gates").mkdir(parents=True)
    (tmp_path / "scripts" / "forge" / "commit_master.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def test_a_writable_enforcement_surface_is_advisory(tmp_path: Path) -> None:
    report = pt.detect_tier(_repo(tmp_path))

    assert report.tier == pt.TIER_ADVISORY
    assert report.writable, "the verdict must carry the evidence that produced it"
    assert not report.is_enforced


def test_the_real_repo_today_is_advisory() -> None:
    """Not a hypothetical. This asserts the live finding from 2026-09-19.

    If this ever fails, the cage started binding this process - which is the goal,
    and the moment to update it deliberately rather than let it drift green.
    """
    report = pt.detect_tier(Path(__file__).resolve().parents[1])

    assert report.tier == pt.TIER_ADVISORY
    assert ".git/config" in report.writable


def test_unwritable_surface_with_privilege_is_locked_not_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An admin can take ownership, so a lock it could undo is not isolation."""
    monkeypatch.setattr(pt, "probe_path", lambda _p: False)
    monkeypatch.setattr(pt, "is_privileged", lambda: True)

    report = pt.detect_tier(_repo(tmp_path))

    assert report.tier == pt.TIER_LOCKED
    assert report.is_enforced
    assert report.writable == ()


def test_unwritable_surface_without_privilege_is_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pt, "probe_path", lambda _p: False)
    monkeypatch.setattr(pt, "is_privileged", lambda: False)

    report = pt.detect_tier(_repo(tmp_path))

    assert report.tier == pt.TIER_ISOLATED
    assert report.summary() == "Protection: Isolated"


def test_one_writable_path_is_enough_to_lose_the_tier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The surface is only as strong as its weakest member: .git/config alone
    is enough, because `git config core.hooksPath` disables every hook."""
    monkeypatch.setattr(pt, "is_privileged", lambda: False)
    monkeypatch.setattr(pt, "probe_path", lambda p: p.name == "config")

    report = pt.detect_tier(_repo(tmp_path))

    assert report.tier == pt.TIER_ADVISORY
    assert report.writable == (".git/config",)


def test_a_missing_surface_is_not_treated_as_protected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Absence is not evidence. An empty directory must not read as safe."""
    monkeypatch.setattr(pt, "is_privileged", lambda: False)

    report = pt.detect_tier(tmp_path)

    assert report.tier == pt.TIER_ADVISORY
    assert len(report.missing) == len(pt.ENFORCEMENT_PATHS)
    assert report.checked == ()


def test_the_word_protected_never_appears_without_a_verified_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pt, "is_privileged", lambda: False)

    advisory = pt.detect_tier(tmp_path).summary().lower()

    assert "advisory" in advisory
    assert "protected" not in advisory


def test_probing_never_truncates_the_file_it_probes(tmp_path: Path) -> None:
    """A probe that damaged its own evidence would be the ruler breaking the thing
    it measures - the exact failure catalogued elsewhere in this repo."""
    _repo(tmp_path)
    target = tmp_path / ".git" / "config"
    target.write_text("[core]\n\trepositoryformatversion = 0\n", encoding="utf-8")
    before = target.read_bytes()

    assert pt.probe_path(target) is True
    assert target.read_bytes() == before


def test_probing_a_directory_leaves_nothing_behind(tmp_path: Path) -> None:
    _repo(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    before = sorted(p.name for p in hooks.iterdir())

    assert pt.probe_path(hooks) is True
    assert sorted(p.name for p in hooks.iterdir()) == before


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits; Windows uses ACLs")
def test_a_read_only_file_really_does_refuse_the_probe(tmp_path: Path) -> None:
    """The probe must react to real permissions, not just to monkeypatching."""
    _repo(tmp_path)
    target = tmp_path / "agent_safety.toml"
    target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    try:
        if os.geteuid() == 0:
            pytest.skip("root ignores mode bits; that is what TIER_LOCKED records")
        assert pt.probe_path(target) is False
    finally:
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
