import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner
import typer

from thomas.browser.p019_browser_profile_create_delete_list import (
    BrowserProfileConfigError,
    CreateBrowserProfileRequest,
    DeleteBrowserProfileRequest,
    InvalidProfileNameError,
    ListBrowserProfilesRequest,
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
    create_browser_profile,
    delete_browser_profile,
    list_browser_profiles,
)

from thomas.cli.commands.browser.p019_browser_profile_create_delete_list import profile_app


def test_core_create_list_delete_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles_root = tmp_path / "profiles"
    monkeypatch.setenv("THOMAS_BROWSER_PROFILES_DIR", str(profiles_root))

    create_result = create_browser_profile(CreateBrowserProfileRequest(name="alpha"))
    assert create_result.profile.name == "alpha"
    assert create_result.profile.kind == "dir"
    assert create_result.profile.path == profiles_root / "alpha"
    assert create_result.profile.path.exists()

    list_result = list_browser_profiles(ListBrowserProfilesRequest())
    assert [(p.name, p.kind) for p in list_result.profiles] == [("alpha", "dir")]

    delete_result = delete_browser_profile(DeleteBrowserProfileRequest(name="alpha"))
    assert delete_result.deleted is True
    assert not (profiles_root / "alpha").exists()

    list_result2 = list_browser_profiles(ListBrowserProfilesRequest())
    assert list_result2.profiles == []


def test_core_rejects_invalid_profile_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_BROWSER_PROFILES_DIR", str(tmp_path / "profiles"))
    with pytest.raises(InvalidProfileNameError):
        create_browser_profile(CreateBrowserProfileRequest(name="../evil"))


def test_core_create_fails_if_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles_root = tmp_path / "profiles"
    monkeypatch.setenv("THOMAS_BROWSER_PROFILES_DIR", str(profiles_root))

    create_browser_profile(CreateBrowserProfileRequest(name="alpha"))
    with pytest.raises(ProfileAlreadyExistsError):
        create_browser_profile(CreateBrowserProfileRequest(name="alpha"))


def test_core_delete_fails_if_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles_root = tmp_path / "profiles"
    monkeypatch.setenv("THOMAS_BROWSER_PROFILES_DIR", str(profiles_root))

    with pytest.raises(ProfileNotFoundError):
        delete_browser_profile(DeleteBrowserProfileRequest(name="missing"))


def test_core_config_error_when_root_is_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root_file = tmp_path / "not_a_dir"
    root_file.write_text("nope")
    monkeypatch.setenv("THOMAS_BROWSER_PROFILES_DIR", str(root_file))

    with pytest.raises(BrowserProfileConfigError):
        list_browser_profiles(ListBrowserProfilesRequest())


def test_core_can_delete_symlink_profile_safely(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profiles_root = tmp_path / "profiles"
    monkeypatch.setenv("THOMAS_BROWSER_PROFILES_DIR", str(profiles_root))
    profiles_root.mkdir(parents=True, exist_ok=True)

    # Create a real target directory outside profiles_root and a symlink entry inside profiles_root.
    target = tmp_path / "target_dir"
    target.mkdir()
    (target / "keep.txt").write_text("keep")

    link = profiles_root / "symprof"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not supported in this environment.")

    listed = list_browser_profiles(ListBrowserProfilesRequest()).profiles
    assert ("symprof", "symlink") in [(p.name, p.kind) for p in listed]

    # Deleting the profile should remove the symlink, not the target dir.
    delete_browser_profile(DeleteBrowserProfileRequest(name="symprof"))
    assert not os.path.lexists(str(link))
    assert target.exists()
    assert (target / "keep.txt").exists()


def test_cli_json_happy_path(tmp_path: Path) -> None:
    profiles_root = tmp_path / "profiles"
    runner = CliRunner()
    cmd = typer.main.get_command(profile_app)

    res = runner.invoke(
        cmd,
        ["create", "beta", "--json"],
        env={"THOMAS_BROWSER_PROFILES_DIR": str(profiles_root)},
    )
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["action"] == "create"
    assert payload["profile"]["name"] == "beta"
    assert payload["profile"]["kind"] == "dir"

    res2 = runner.invoke(
        cmd,
        ["list", "--json"],
        env={"THOMAS_BROWSER_PROFILES_DIR": str(profiles_root)},
    )
    assert res2.exit_code == 0, res2.stdout
    payload2 = json.loads(res2.stdout)
    assert payload2["ok"] is True
    assert payload2["count"] == 1
    assert payload2["profiles"][0]["name"] == "beta"

    res3 = runner.invoke(
        cmd,
        ["delete", "beta", "--json"],
        env={"THOMAS_BROWSER_PROFILES_DIR": str(profiles_root)},
    )
    assert res3.exit_code == 0, res3.stdout
    payload3 = json.loads(res3.stdout)
    assert payload3["ok"] is True
    assert payload3["deleted"] is True


def test_cli_json_error_on_invalid_name(tmp_path: Path) -> None:
    runner = CliRunner()
    cmd = typer.main.get_command(profile_app)

    res = runner.invoke(
        cmd,
        ["create", "../evil", "--json"],
        env={"THOMAS_BROWSER_PROFILES_DIR": str(tmp_path / "profiles")},
    )
    assert res.exit_code == 2
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_profile_name"
