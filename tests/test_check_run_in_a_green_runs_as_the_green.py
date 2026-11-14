"""``check.run`` in a green runs its checks as the green, and nowhere else does.

The test run's tripwire (``tests/conftest.py``) fails a run when your real Thomas
data files change while it goes on. It stands down only for a run started with
``THOMAS_AGENT_ID=thomas-green``, because in a green the watched folder is the
caged Thomas's own, and that server keeps writing its database while its Build
team runs the tests. The caged shell gives a green's commands that id
(``scripts/cage/shell_runner.py`` ``child_env``); ``check.run`` did not. Measured
2026-10-13: a Build team applying a reviewed patch ran its 162 tests with
``check.run``, all passed, and pytest still exited failed because the caged
server's own ``thomas.db-wal`` went away during the five-minute run. The team
lost two runs to it.

The marking disarms the tripwire, so it must never reach a check that is not in
a green: a green is a folder in the green root's ``work`` that the server made,
with its record in the green root's ``git`` folder, never a project's own files.
And only the cage account's checks are marked. The caged shell, the only thing
that set the id before, always runs as the cage account; a green made by the
Thomas that runs as you has its tests run as you, over your real data folder and
``~/.thomas``, which is exactly what the tripwire is there to watch.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests import conftest as guard
from thomas.core import cage_account, green_place
from thomas.server import green_checkout
from thomas.tools import check_run
from thomas.tools.check_run import CheckRunTool

GREEN_ID = "thomas-green"  # the id scripts/cage/shell_runner.py gives a green's commands
AGENT_ID_KEYS = ("THOMAS_AGENT_ID", "AGENT_ID")


class _Finished:
    """A check that ended at once, so only the environment it was started with matters."""

    pid = 0
    returncode = 0

    def communicate(self, timeout: float | None = None) -> tuple[bytes, None]:
        return b"", None

    def poll(self) -> int:
        return 0


def _env_of_a_check(folder: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The environment ``check.run`` starts its process with, for a check run in *folder*."""
    seen: dict[str, str] = {}

    def _launch(argv: list[str], **kwargs: Any) -> _Finished:
        seen.update(kwargs["env"])
        return _Finished()

    monkeypatch.setattr(check_run.subprocess, "Popen", _launch)
    result = asyncio.run(CheckRunTool(folder).safe_execute({"check": "git_status"}))
    assert result.ok, result.error
    return seen


def _make_green(root: Path, execution_id: str) -> Path:
    """The layout ``green_checkout.create_green`` leaves: a work folder and, apart from it, the server's record."""
    work = root / "work" / execution_id
    work.mkdir(parents=True)
    record = root / "git" / execution_id / green_checkout.METADATA_NAME
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"execution_id": execution_id}), encoding="utf-8")
    return work


def _as_the_cage_account(monkeypatch: pytest.MonkeyPatch, caged: bool) -> None:
    """Which account this process is (tests/conftest.py answers "not the cage" for every test)."""
    monkeypatch.setattr(cage_account, "running_as_cage_account", lambda: caged)


@pytest.fixture
def green_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A green root, as the cage account: the one place the mark belongs, so every refusal below is the place's."""
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "greens"))
    for key in AGENT_ID_KEYS:
        monkeypatch.delenv(key, raising=False)
    _as_the_cage_account(monkeypatch, True)
    return green_checkout.green_root()


def _marked(env: dict[str, str]) -> list[str]:
    return [key for key in AGENT_ID_KEYS if str(env.get(key) or "").strip() == GREEN_ID]


# -- in a green, the check runs as the green ---------------------------------


@pytest.mark.parametrize("parent_id", [None, "claude"], ids=["no-agent-id", "another-agent-id"])
@pytest.mark.parametrize("where", ["", "thomas/tools"], ids=["the-green", "a-folder-in-it"])
def test_a_check_in_a_green_runs_as_the_green(
    green_root: Path, monkeypatch: pytest.MonkeyPatch, where: str, parent_id: str | None
) -> None:
    folder = _make_green(green_root, "exec-1") / where
    folder.mkdir(parents=True, exist_ok=True)
    for key in AGENT_ID_KEYS:
        if parent_id:
            monkeypatch.setenv(key, parent_id)

    env = _env_of_a_check(folder, monkeypatch)

    assert env.get("THOMAS_AGENT_ID") == GREEN_ID and env.get("AGENT_ID") == GREEN_ID, {
        key: env.get(key) for key in AGENT_ID_KEYS
    }


def test_a_green_found_where_green_checkout_makes_greens_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``THOMAS_GREEN_ROOT``: greens live in the data folder, and check.run looks in the same place."""
    for key in (green_checkout.GREEN_ROOT_ENV, "THOMAS_PROFILE", *AGENT_ID_KEYS):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    _as_the_cage_account(monkeypatch, True)
    green = _make_green(green_checkout.green_root(), "exec-default")

    assert _marked(_env_of_a_check(green, monkeypatch)) == list(AGENT_ID_KEYS)


def test_the_tripwire_keeps_a_green_checks_result_and_stays_armed_outside(
    green_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asked of the tripwire's own reader (``tests/conftest.py``), so a change on either side shows here."""
    green = _make_green(green_root, "exec-2")
    outside = tmp_path / "project"
    outside.mkdir()

    assert guard._running_in_a_green(_env_of_a_check(green, monkeypatch))
    assert not guard._running_in_a_green(_env_of_a_check(outside, monkeypatch))


def test_the_green_checks_own_test_process_runs_as_the_green(green_root: Path) -> None:
    """End to end: the pytest process a check starts in a green sees the marking."""
    green = _make_green(green_root, "exec-3")
    (green / "test_who.py").write_text(
        "import os\n\n\ndef test_who():\n"
        f"    assert os.environ.get('THOMAS_AGENT_ID') == {GREEN_ID!r}\n"
        f"    assert os.environ.get('AGENT_ID') == {GREEN_ID!r}\n",
        encoding="utf-8",
    )

    result = asyncio.run(
        CheckRunTool(green).safe_execute({"check": "pytest", "args": ["-q", "-p", "no:cacheprovider", "test_who.py"]})
    )

    assert result.ok, result.error
    assert result.data["exit_code"] == 0, result.data["output"][-1500:]


# -- anywhere else, the tripwire stays armed ---------------------------------


@pytest.mark.parametrize("inherited", [None, GREEN_ID], ids=["no-agent-id", "an-inherited-green-id"])
def test_a_green_check_under_your_own_account_stays_armed(
    green_root: Path, monkeypatch: pytest.MonkeyPatch, inherited: str | None
) -> None:
    """A green made by the Thomas that runs as you: its tests run as you, and the tripwire watches your real data
    folder and ~/.thomas. Standing it down there would hide a real leak, so the check is not marked, and an id it
    inherited is not passed on either."""
    green = _make_green(green_root, "exec-7")
    _as_the_cage_account(monkeypatch, False)
    for key in AGENT_ID_KEYS:
        if inherited:
            monkeypatch.setenv(key, inherited)

    env = _env_of_a_check(green, monkeypatch)

    assert _marked(env) == []
    assert not guard._running_in_a_green(env)


def test_a_check_outside_a_green_is_not_marked(
    green_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    assert _marked(_env_of_a_check(project, monkeypatch)) == []


def test_another_agent_id_outside_a_green_is_passed_on_unchanged(
    green_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    for key in AGENT_ID_KEYS:
        monkeypatch.setenv(key, "claude")

    env = _env_of_a_check(project, monkeypatch)

    assert [env.get(key) for key in AGENT_ID_KEYS] == ["claude", "claude"]


@pytest.mark.parametrize("inherited", [GREEN_ID, f" {GREEN_ID} "], ids=["exact", "padded"])
def test_a_check_outside_a_green_does_not_pass_on_a_green_id_it_inherited(
    green_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inherited: str
) -> None:
    """Before this change check.run copied its own environment whole, so a process that carried the green's id
    (a server started from a green's shell, say) disarmed the tripwire for every check it ran, in any project."""
    project = tmp_path / "project"
    project.mkdir()
    for key in AGENT_ID_KEYS:
        monkeypatch.setenv(key, inherited)

    env = _env_of_a_check(project, monkeypatch)

    assert _marked(env) == []
    assert not guard._running_in_a_green(env)


def test_a_project_holding_files_named_like_a_greens_record_is_not_a_green(
    green_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project writes its own files; none of them can make it a green."""
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    for record in (project / green_checkout.METADATA_NAME, project / ".git" / green_checkout.METADATA_NAME):
        record.write_text(json.dumps({"execution_id": "project"}), encoding="utf-8")
    # The whole layout of a green, built outside the green root: the shape alone is not a green.
    look_alike = _make_green(tmp_path / "elsewhere" / "green", "exec-4")

    assert _marked(_env_of_a_check(project, monkeypatch)) == []
    assert _marked(_env_of_a_check(look_alike, monkeypatch)) == []


@pytest.mark.parametrize("key", [green_checkout.GREEN_ROOT_ENV, "THOMAS_DATA_DIR"], ids=["green-root", "data-dir"])
def test_a_green_root_named_by_a_relative_path_is_not_trusted(
    green_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    """A relative root is read against the working folder, so a project the check runs from could hold the whole
    layout of a green, record and all, and be taken for one."""
    project = tmp_path / "project"
    project.mkdir()
    for name in (green_checkout.GREEN_ROOT_ENV, "THOMAS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(key, ".")
    green = _make_green(project if key == green_checkout.GREEN_ROOT_ENV else project / "green", "x")
    monkeypatch.chdir(project)

    assert green_place.green_of(green) == ""
    assert _marked(_env_of_a_check(green, monkeypatch)) == []


def test_a_folder_in_the_green_root_the_server_did_not_make_is_not_a_green(
    green_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Something other than the server made this folder in ``work`` (the cage account may write there): no record."""
    stray = green_root / "work" / "exec-5"
    (stray / ".git").mkdir(parents=True)
    for record in (stray / green_checkout.METADATA_NAME, stray / ".git" / green_checkout.METADATA_NAME):
        record.write_text(json.dumps({"execution_id": "exec-5"}), encoding="utf-8")

    assert _marked(_env_of_a_check(stray, monkeypatch)) == []
    assert _marked(_env_of_a_check(green_root / "work", monkeypatch)) == []
    assert _marked(_env_of_a_check(green_root, monkeypatch)) == []


@pytest.mark.skipif(os.name != "nt", reason="a directory junction is a Windows link")
def test_a_link_in_the_green_root_does_not_make_the_folder_it_leads_to_a_green(
    green_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import _winapi

    project = tmp_path / "project"
    project.mkdir()
    _make_green(green_root, "exec-6")
    link = green_root / "work" / "exec-6" / "linked"
    _winapi.CreateJunction(str(project), str(link))

    # green_of resolves the link itself; check.run also resolves its root before asking.
    assert green_place.green_of(link) == ""
    assert _marked(_env_of_a_check(link, monkeypatch)) == []
