"""A committed starting repository shared by landing test fixtures."""

import os
import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest

from tests.green_support import git, make_blue
from thomas.core.git_launcher import real_git_first


@pytest.fixture(scope="module", autouse=True)
def isolated_landing_git():
    with pytest.MonkeyPatch.context() as patch:
        for name in list(os.environ):
            if name.upper().startswith("GIT_"):
                patch.delenv(name)
        yield


def landing_blue_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _landing_blue_template(tmp_path_factory.getbasetemp())


@cache
def _landing_blue_template(base: Path) -> Path:
    root = base / "landing-template"
    root.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        for name in list(os.environ):
            if name.upper().startswith("GIT_"):
                patch.delenv(name)
        patch.setenv("PATH", real_git_first(os.environ)["PATH"])
        repo = make_blue(root)
        git(repo, "checkout", "-q", "-b", "dev")
        git(repo, "config", "core.autocrlf", "true" if os.name == "nt" else "false")
        hooks = repo / ".git" / "hooks"
        if hooks.exists():
            shutil.rmtree(hooks)
        return repo


def copy_blue(template: Path, root: Path) -> Path:
    return Path(shutil.copytree(template, root / "blue"))


def prepare_green_root(root: Path) -> Path:
    """Create the fixture's private green directories before checkout."""
    for name in ("work", "git"):
        (root / name).mkdir(parents=True)
    return root


def checkout_bytes(repo: Path, root: Path, paths: list[str], autocrlf: str) -> dict[str, bytes]:
    root.mkdir()
    subprocess.run(
        [
            "git",
            "-c",
            f"core.autocrlf={autocrlf}",
            "checkout-index",
            f"--prefix={root.as_posix()}/",
            "--",
            *paths,
        ],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return {path: (root / path).read_bytes() for path in paths}
