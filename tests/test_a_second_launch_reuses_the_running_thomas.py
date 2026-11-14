"""Launching Thomas a second time used to stop the first Thomas, whatever it was doing.

run-ui.ps1 force-ended any Thomas server on the port before starting its own. A
second double-click, or one ``thomas://`` link, cut off a Build in flight; the
server's own restart route refuses in that case with a 409. Now a Thomas that
answers is told apart by what /api/health says it is: the copy being launched is
reused, another copy (a different folder, version or commit) is replaced unless it
is mid-Build, and a Build is never stopped. These tests point the launcher's own
decision functions at small stand-in servers that answer the two routes it reads,
and stop no process. A server started before the code changed is next door.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.launcher_powershell_support import RUN_UI, needs_windows_powershell, ps_path, run_functions
from tests.launcher_server_plan_support import (
    BUSY,
    ELSEWHERE,
    IDLE,
    LEGACY_BUSY,
    LEGACY_RECORDING,
    LOCAL_COMMIT,
    LOCAL_ROOT,
    LOCAL_VERSION,
    health,
    plan_lines,
    port_of,
)


# The path is this copy's, so the command works from any folder (the launch log is opened from Explorer).
def restart_hint(port: int) -> str:
    """The command the log gives: this copy's own path, and the port it is about, so it acts on that Thomas and no other."""
    return (
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "{LOCAL_ROOT}\\scripts\\run-ui.ps1" -Restart -Port {port}'
    )


# name -> (what /api/health says, what /api/evolve/agent/status says: a dict, an HTTP error status, a raw body,
# or None for "no such route")
CASES: dict[str, tuple[dict, dict | int | str | None]] = {
    "same copy": (health(), IDLE),
    "same copy, path spelled differently": (health(root="c:/apps/THOMAS/"), IDLE),
    # An older server names no cause; the others name what /api/health lists under "degraded".
    "same copy, degraded": (health(status="degraded"), IDLE),
    "same copy, degraded, empty list": (health(status="degraded", degraded=[]), IDLE),
    "same copy, degraded, no model sign-in": (health(status="degraded", degraded=["model_auth"]), IDLE),
    "same copy, degraded, boot diagnostic": (health(status="degraded", degraded=["memory"]), IDLE),
    "same copy, degraded, both": (health(status="degraded", degraded=["model_auth", "memory"]), IDLE),
    "same copy, building": (health(), BUSY),
    "same copy, legacy session running": (health(), LEGACY_BUSY),
    "same copy, legacy session recording": (health(), LEGACY_RECORDING),
    "other folder": (health(root=ELSEWHERE), IDLE),
    "other folder, building": (health(root=ELSEWHERE), BUSY),
    "other folder, legacy session running": (health(root=ELSEWHERE), LEGACY_BUSY),
    # No Build status route at all: a Thomas that predates Build has no run to cut off.
    "other folder, no build route": (health(root=ELSEWHERE), None),
    "older build, no build route": (health(root=ELSEWHERE, build=False, version="9.0.0"), None),
    # Answers that are not "no such route" and do not say whether a Build runs.
    "other folder, status error": (health(root=ELSEWHERE), 500),
    "other folder, status refused": (health(root=ELSEWHERE), 403),
    "other folder, status without running": (health(root=ELSEWHERE), {"ok": True}),
    "other folder, status is not json": (health(root=ELSEWHERE), "<html>not thomas</html>"),
    "other version": (health(version="9.8.0"), IDLE),
    "other commit": (health(commit="bbbb2222"), IDLE),
    "older build": (health(build=False), IDLE),
    "not thomas": ({"ok": True}, None),
}


@pytest.fixture(scope="module")
def plans(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    return plan_lines(CASES, tmp_path_factory.mktemp("reuse"))


@needs_windows_powershell
def test_the_copy_being_launched_is_used_not_stopped(plans: dict[str, str]) -> None:
    line = plans["same copy"]
    port = port_of(plans, "same copy")

    assert line.startswith("same copy|attach|"), plans["raw"]
    # The message says which build it is using, so a stale one is visible.
    assert f"Using the Thomas already running on port {port} (v9.9.9 dev@aaaa1111, {LOCAL_ROOT})" in line
    # And how to replace it, as the full command: a bare .ps1 is refused by the default execution policy.
    assert f"To replace it run: {restart_hint(port)}" in line
    assert plans["left:same copy"] == "0"
    assert plans["same copy, path spelled differently"].startswith("same copy, path spelled differently|attach|")
    assert plans["older build"].startswith("older build|attach|"), plans["raw"]
    # Building or not, without a restart asked for nothing is stopped.
    assert plans["same copy, building"].startswith("same copy, building|attach|")


@needs_windows_powershell
def test_a_degraded_thomas_is_not_announced_as_healthy(plans: dict[str, str]) -> None:
    line = plans["same copy, degraded"]

    assert line.startswith("same copy, degraded|attach|"), plans["raw"]
    assert "(reporting degraded)" in line
    assert "(reporting degraded)" not in plans["same copy"]
    # It is reused, not stopped (that would end a chat in flight), and the plan says it is degraded so the launch can say so.
    assert plans["degraded:same copy, degraded"] == "1", plans["raw"]
    for name in ("same copy", "same copy, building", "other folder", "same copy, degraded -ReplaceIt"):
        assert plans[f"degraded:{name}"] == "0", (name, plans["raw"])


@needs_windows_powershell
def test_a_thomas_with_no_model_sign_in_is_not_called_broken_but_any_other_degraded_cause_is(
    plans: dict[str, str],
) -> None:
    """Without a model sign-in /api/health says degraded for every stranger who has not signed in, and a restart cannot change that.

    Exit 7 is the shortcut telling you part of Thomas is not working and to restart it, so it is for a cause a
    restart or repair can change: a boot diagnostic, or a server that does not say what is wrong.
    """
    for name, broken in (
        ("same copy, degraded", "1"),
        ("same copy, degraded, empty list", "1"),
        ("same copy, degraded, no model sign-in", "0"),
        ("same copy, degraded, boot diagnostic", "1"),
        ("same copy, degraded, both", "1"),
    ):
        assert plans[name].startswith(f"{name}|attach|"), plans["raw"]
        assert plans[f"degraded:{name}"] == broken, (name, plans["raw"])
        # Still reused, and the log still says what the server reports.
        assert "(reporting degraded)" in plans[name], plans["raw"]


@needs_windows_powershell
def test_a_thomas_from_another_folder_is_replaced_and_says_which_is_running(plans: dict[str, str]) -> None:
    line = plans["other folder"]
    port = port_of(plans, "other folder")

    assert line.startswith("other folder|replace|"), plans["raw"]
    assert (
        f"Replacing the Thomas on port {port} (v9.9.9 dev@aaaa1111, {ELSEWHERE}); "
        f"it is not this copy (v9.9.9, {LOCAL_ROOT})." in line
    )
    # The same version in another folder used to be attached to silently; the version alone cannot tell them apart.
    assert plans["other folder -ReplaceIt"] == "other folder -ReplaceIt|replace|", plans["raw"]


@needs_windows_powershell
def test_a_thomas_on_another_version_or_commit_is_replaced(plans: dict[str, str]) -> None:
    assert plans["other version"].startswith("other version|replace|Replacing the Thomas"), plans["raw"]
    assert "v9.8.0" in plans["other version"] and f"v{LOCAL_VERSION}" in plans["other version"]
    assert plans["other commit"].startswith("other commit|replace|Replacing the Thomas"), plans["raw"]
    # Same folder, same version: the commits are what differ, and both are named.
    assert "@bbbb2222" in plans["other commit"] and f"@{LOCAL_COMMIT}" in plans["other commit"]


@needs_windows_powershell
def test_a_build_is_never_stopped_for_another_copy_or_for_a_restart(plans: dict[str, str]) -> None:
    other = plans["other folder, building"]

    assert other.startswith("other folder, building|attach|"), plans["raw"]
    assert "is not this copy" in other and "running 1 Build run(s)" in other and "left running" in other
    assert f"then run: {restart_hint(port_of(plans, 'other folder, building'))}" in other
    # It is open, but it is not what was launched: the exit code and the shortcut's message say so.
    assert plans["left:other folder, building"] == "1"
    asked = plans["same copy, building -ReplaceIt"]
    assert asked.startswith("same copy, building -ReplaceIt|refuse|"), plans["raw"]
    assert "running 1 Build run(s)" in asked
    assert plans["same copy -ReplaceIt"] == "same copy -ReplaceIt|replace|", plans["raw"]


@needs_windows_powershell
def test_a_server_running_only_a_legacy_session_still_counts_as_building(plans: dict[str, str]) -> None:
    """The top-level flags and runs[] come from different places in the server, and can disagree."""
    for name in ("same copy, legacy session running", "same copy, legacy session recording"):
        assert plans[name].startswith(f"{name}|attach|"), plans["raw"]
        assert plans[f"left:{name}"] == "0"
        asked = plans[f"{name} -ReplaceIt"]
        assert asked.startswith(f"{name} -ReplaceIt|refuse|") and "running 1 Build run(s)" in asked, plans["raw"]
    other = plans["other folder, legacy session running"]
    assert other.startswith("other folder, legacy session running|attach|"), plans["raw"]
    assert "running 1 Build run(s)" in other and plans["left:other folder, legacy session running"] == "1"


WILL_NOT_SAY = (
    "other folder, status error",
    "other folder, status refused",
    "other folder, status without running",
    "other folder, status is not json",
)


@needs_windows_powershell
@pytest.mark.parametrize("name", WILL_NOT_SAY)
def test_a_server_that_will_not_say_what_it_runs_is_restarted_only_on_request(plans: dict[str, str], name: str) -> None:
    """An error, a refusal, and a 200 that has no ``running`` in it all leave a possible Build alone."""
    unasked = plans[name]
    assert unasked.startswith(f"{name}|attach|"), plans["raw"]
    assert "would not say whether a Build is running, so it was left running" in unasked
    assert plans[f"left:{name}"] == "1"
    asked = plans[f"{name} -ReplaceIt"]
    assert asked.startswith(f"{name} -ReplaceIt|replace|"), plans["raw"]
    assert "would not say whether a Build is running" in asked


@needs_windows_powershell
@pytest.mark.parametrize("name", ["other folder, no build route", "older build, no build route"])
def test_a_thomas_with_no_build_route_is_replaced_as_it_always_was(plans: dict[str, str], name: str) -> None:
    """A 404 on the Build status route is an answer: that Thomas predates Build, so upgrading replaces it."""
    assert plans[name].startswith(f"{name}|replace|Replacing the Thomas on port"), plans["raw"]
    assert plans[f"left:{name}"] == "0"
    assert plans[f"{name} -ReplaceIt"] == f"{name} -ReplaceIt|replace|", plans["raw"]


@needs_windows_powershell
def test_a_busy_port_that_is_not_thomas_or_a_free_port_is_a_plain_start(plans: dict[str, str]) -> None:
    port = port_of(plans, "not thomas")
    for flag in ("", " -ReplaceIt"):
        line = plans["not thomas" + flag]
        assert line.startswith(f"not thomas{flag}|start|Port {port} is in use, but nothing there answered"), plans[
            "raw"
        ]
        # It cannot be told from a busy one, so the message says what replacing it costs, and what is left alone.
        assert (
            "is stopped and replaced, which ends any Build it is running; any other program there is left alone."
            in line
        ), plans["raw"]
        assert plans["nothing there" + flag] == f"nothing there{flag}|start|", plans["raw"]


@pytest.mark.skipif(not shutil.which("git"), reason="git is not installed")
@needs_windows_powershell
def test_the_local_commit_is_the_one_health_reports_or_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], cwd=repo, check=True, capture_output=True)
    expected = subprocess.run(
        [*git, "rev-parse", "--short=8", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    plain = tmp_path / "not a repository"
    plain.mkdir()

    out = run_functions(
        RUN_UI,
        ["Get-CommandPathAny", "Get-LocalGitCommit"],
        f"$Root = {ps_path(repo)}\n'repo: [' + (Get-LocalGitCommit) + ']'\n$Root = {ps_path(plain)}\n'plain: [' + (Get-LocalGitCommit) + ']'",
        tmp_path,
    )

    assert f"repo: [{expected}]" in out, out
    assert "plain: []" in out, out


def test_the_reuse_decision_comes_before_anything_is_written_or_stopped() -> None:
    text = RUN_UI.read_text(encoding="utf-8")

    assert "[switch]$Restart" in text
    decision = text.index("\n$gateExit = Invoke-ExistingServerGate\n")
    assert decision < text.index("\nEnsure-ThomasProtocolRegistration\n")
    assert decision < text.index("\n$venvExit = Ensure-ThomasVenv\n")
    assert decision < text.index("Stop-ThomasServerOnPort $Port | Out-Null")
