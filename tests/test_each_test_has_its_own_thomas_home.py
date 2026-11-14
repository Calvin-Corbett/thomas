"""Implicit skill and Work paths must resolve inside each test's own home."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.skills import discover_native_skills
from thomas.work import WorkStore


def test_git_commits_with_this_tests_home_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = Path.home()
    config = home / ".gitconfig"
    assert config.is_file()
    assert os.environ["GIT_CONFIG_GLOBAL"] == str(config)
    assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"
    assert home != tmp_path
    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(key, raising=False)

    def git(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    git("init", "-q")
    (tmp_path / "example.txt").write_text("test\n", encoding="utf-8")
    git("add", "example.txt")
    git("commit", "-qm", "test home identity")
    assert git("log", "-1", "--format=%an <%ae> | %cn <%ce>") == (
        "Thomas Test <thomas-test@example.invalid> | Thomas Test <thomas-test@example.invalid>"
    )


def test_implicit_skill_discovery_uses_this_tests_home(tmp_path: Path) -> None:
    home = Path.home()
    assert home != tmp_path and home not in tmp_path.parents and tmp_path not in home.parents
    assert list(tmp_path.iterdir()) == []
    skill = home / ".thomas" / "skills" / "isolated-home-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: isolated-home-skill\ndescription: Test-only skill.\n---\n\n# Isolated\n",
        encoding="utf-8",
    )

    bundles, roots = discover_native_skills(cwd=tmp_path)

    assert Path.home() == home
    assert any(bundle.skill_file == str(skill) for bundle in bundles)
    assert str(home / ".thomas" / "skills") in roots
    assert all(root.startswith(str(home)) or root.startswith(str(tmp_path)) for root in roots)


def test_implicit_work_migration_uses_this_tests_home(tmp_path: Path) -> None:
    home = Path.home()
    assert home != tmp_path and home not in tmp_path.parents and tmp_path not in home.parents
    assert list(tmp_path.iterdir()) == []
    config = SimpleNamespace(memory=SimpleNamespace(root_path=tmp_path / "workspace"))

    legacy_apps = home / ".thomas" / "freedom_transit" / "work_apps.json"
    legacy_apps.parent.mkdir(parents=True)
    legacy_apps.write_text(json.dumps({"apps": [{"id": "test-only-app", "name": "Test Only"}]}), encoding="utf-8")

    store = WorkStore.from_config(config)

    assert store._user_work_apps_path == legacy_apps
    assert any(app["id"] == "test-only-app" for app in store.list_apps())
    assert store.global_skills_root == home / ".thomas" / "skills"
    assert store.state_path.is_file()
