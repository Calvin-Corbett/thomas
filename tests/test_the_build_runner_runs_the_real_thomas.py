"""The Build runner imports the Thomas that launched it, not the project it edits.

`_agent_launch` puts the server's own package root first on PYTHONPATH, but the
runner starts with `python -m ...` inside the project folder, and `-m` puts the
working folder ahead of PYTHONPATH. In a project that is a copy of Thomas (a
worktree Thomas is asked to improve), the copy's `thomas/` package won: the
runner ran the code it was in the middle of editing, and every "is this Thomas's
own source?" check pointed at the copy instead of the running install.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.forge.anvil.forge_code_runner import release_safe_path_for_children
from thomas.server.routes.evolve_agent_runtime import _agent_launch

_REPO = Path(__file__).resolve().parents[1]


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        child_environment=lambda env: env,
        engine="funnel",
        family="gpt",
        agent="thomas",
        dispatch_model="gpt:gpt-5.6-sol",
        gpt_profile="openai_codex",
        autonomy_level=3,
        file_access="project",
        memory=True,
        guardrails="guarded",
        token_economy="optimal",
    )


def test_a_thomas_copy_in_the_project_does_not_shadow_the_real_thomas(tmp_path: Path) -> None:
    project = tmp_path / "copy-of-thomas"
    decoy = project / "thomas"
    decoy.mkdir(parents=True)
    (decoy / "__init__.py").write_text("DECOY = True\n", encoding="utf-8")

    _cmd, env = _agent_launch(_settings(), project, "fc_test", package_root=_REPO)
    probe = subprocess.run(
        [sys.executable, "-c", "import thomas; print(thomas.__file__)"],
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert probe.returncode == 0, probe.stderr
    imported = Path(probe.stdout.strip()).resolve()
    assert decoy.resolve() not in imported.parents, f"runner imported the project copy: {imported}"
    assert imported == (_REPO / "thomas" / "__init__.py").resolve()


def test_the_checks_the_runner_launches_still_import_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "made_by_the_agent.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONSAFEPATH", "1")

    release_safe_path_for_children()
    check = subprocess.run(
        [sys.executable, "-c", "import made_by_the_agent; print(made_by_the_agent.__file__)"],
        cwd=str(project),
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert "PYTHONSAFEPATH" not in os.environ
    assert check.returncode == 0, check.stderr
    assert Path(check.stdout.strip()).resolve().parent == project.resolve()
