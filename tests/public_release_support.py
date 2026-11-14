"""Fixture repositories for the public release tests: a development repo, a bare "public" repo, and a clean git setup.

Everything lives under a pytest temp folder. No test here reaches GitHub, the real checkout or any real git settings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.core.git_process import run_git

REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = (
    "# Changelog\n\n## [Unreleased]\n\n## [1.2.3] - 2026-11-03\n\n"
    "- **First change.** Details nobody needs in a title.\n- **Second change.** More details.\n\n"
    "## [1.2.2] - 2026-10-01\n\n- **Older change.** Gone by now.\n"
)
DEV_FILES = {
    "README.md": "hello\n",
    "CHANGELOG.md": CHANGELOG,
    "OWNER_STEPS.md": "steps\n",
    "thomas/__init__.py": '__version__ = "1.2.3"\n',
    "thomas/security/__init__.py": "",
    "thomas/security/secret_canaries.py": "def plant():\n    return 1\n",
    "tests/test_secret_canaries.py": "def test_x():\n    pass\n",
    "docs/ops/public_exclude.txt": (REPO_ROOT / "docs/ops/public_exclude.txt").read_text(encoding="utf-8"),
}
IDENTITY = ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false")


def ok_preflight(_tree: Path) -> tuple[bool, str]:
    return True, "every check passed"


def sh(cwd: Path, *args: str) -> str:
    result = run_git(list(args), cwd=cwd, timeout=120)
    assert result.ok, f"git {' '.join(args)}: {result.message()}"
    return result.output()


def commit_all(repo: Path, message: str) -> str:
    sh(repo, "add", "-A")
    sh(repo, *IDENTITY, "commit", "-q", "--allow-empty", "-m", message)
    return sh(repo, "rev-parse", "HEAD")


def make_dev(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    dev = tmp_path / "dev"
    for rel, text in {**DEV_FILES, **(extra or {})}.items():
        (dev / rel).parent.mkdir(parents=True, exist_ok=True)
        (dev / rel).write_text(text, encoding="utf-8")
    sh(tmp_path, "init", "-q", "-b", "dev", str(dev))
    commit_all(dev, "a private commit message nobody should see")
    return dev


def make_public(tmp_path: Path) -> tuple[Path, str]:
    """A bare repository whose main holds one older commit. Returns it and that commit."""
    seed = tmp_path / "seed"
    (seed / "docs").mkdir(parents=True)
    (seed / "README.md").write_text("an older public readme\n", encoding="utf-8")
    sh(tmp_path, "init", "-q", "-b", "main", str(seed))
    old = commit_all(seed, "older public release")
    bare = tmp_path / "public.git"
    sh(tmp_path, "init", "-q", "--bare", str(bare))
    sh(seed, "push", "-q", str(bare), "main:refs/heads/main")
    return bare, old


def refs(bare: Path) -> dict[str, str]:
    out = sh(bare, "for-each-ref", "--format=%(objectname) %(refname)")
    return {line.split(" ", 1)[1]: line.split(" ", 1)[0] for line in out.splitlines()}


@pytest.fixture(autouse=True)
def clean_git_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Git reads an empty global file, so no signing key, name or hook of this machine reaches a test."""
    config = tmp_path / "global.gitconfig"
    config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return config
