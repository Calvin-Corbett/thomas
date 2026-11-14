"""Local plugin installation refuses links before creating an install destination."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from thomas.plugins.p102_plugin_install_from_local_path import (
    PluginInstallFromLocalPathError,
    PluginInstallFromLocalPathRequest,
    install_plugin_from_local_path,
    run,
)


def _make_plugin(tmp_path: Path) -> Path:
    source = tmp_path / "src_plugin"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nname = "demo_plugin"\nversion = "0.1.0"\n', encoding="utf-8")
    (source / "README.md").write_text("hello", encoding="utf-8")
    return source


def _make_outside_folder(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "owner-secret.txt").write_text("outside stays here", encoding="utf-8")
    return outside


def _make_junction(target: Path, link: Path) -> None:
    import _winapi

    _winapi.CreateJunction(str(target), str(link))
    assert link.is_junction()
    assert not link.is_symlink()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows directory junctions only")
@pytest.mark.parametrize("parent_parts", [(), ("pkg",), ("pkg", "deeper")])
def test_a_junction_anywhere_in_the_plugin_folder_is_refused(tmp_path: Path, parent_parts: tuple[str, ...]) -> None:
    source = _make_plugin(tmp_path)
    outside = _make_outside_folder(tmp_path)
    parent = source.joinpath(*parent_parts)
    parent.mkdir(parents=True, exist_ok=True)
    link = parent / "linked"
    _make_junction(outside, link)
    install_root = tmp_path / "installed"

    with pytest.raises(PluginInstallFromLocalPathError) as caught:
        install_plugin_from_local_path(PluginInstallFromLocalPathRequest(source_path=source, install_root=install_root))

    assert caught.value.code == "unsafe_source_tree"
    assert "junction" in str(caught.value)
    assert caught.value.details["path"] == str(link)
    assert not install_root.exists()
    assert not (install_root / "demo_plugin").exists()
    assert not (install_root / "demo_plugin" / "linked" / "owner-secret.txt").exists()
    assert link.is_junction()
    assert (outside / "owner-secret.txt").read_text(encoding="utf-8") == "outside stays here"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows directory junctions only")
def test_a_junction_that_points_inside_the_plugin_is_refused_too(tmp_path: Path) -> None:
    source = _make_plugin(tmp_path)
    data = source / "data"
    data.mkdir()
    (data / "item.txt").write_text("local", encoding="utf-8")
    link = source / "data_again"
    _make_junction(data, link)
    install_root = tmp_path / "installed"

    with pytest.raises(PluginInstallFromLocalPathError) as caught:
        install_plugin_from_local_path(PluginInstallFromLocalPathRequest(source_path=source, install_root=install_root))

    assert caught.value.code == "unsafe_source_tree"
    assert "junction" in str(caught.value)
    assert caught.value.details["path"] == str(link)
    assert not install_root.exists()
    assert link.is_junction()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows directory junctions only")
def test_the_json_entry_point_reports_the_junction(tmp_path: Path) -> None:
    source = _make_plugin(tmp_path)
    outside = _make_outside_folder(tmp_path)
    link = source / "linked"
    _make_junction(outside, link)
    install_root = tmp_path / "installed"

    result = run({"source_path": str(source), "install_root": str(install_root)})

    assert result["ok"] is False
    assert result["error"]["code"] == "unsafe_source_tree"
    assert "junction" in result["error"]["message"]
    assert result["error"]["details"]["path"] == str(link)
    assert not install_root.exists()
    assert not (install_root / "demo_plugin").exists()
    assert link.is_junction()
    assert (outside / "owner-secret.txt").read_text(encoding="utf-8") == "outside stays here"


def test_a_symbolic_link_is_still_refused(tmp_path: Path) -> None:
    source = _make_plugin(tmp_path)
    outside = _make_outside_folder(tmp_path)
    link = source / "linked_secret.txt"
    try:
        os.symlink(outside / "owner-secret.txt", link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Cannot make a symbolic link here: {exc}")
    install_root = tmp_path / "installed"

    with pytest.raises(PluginInstallFromLocalPathError) as caught:
        install_plugin_from_local_path(PluginInstallFromLocalPathRequest(source_path=source, install_root=install_root))

    assert caught.value.code == "unsafe_source_tree"
    assert "symbolic link" in str(caught.value)
    assert caught.value.details["path"] == str(link)
    assert not install_root.exists()


def test_a_plugin_with_real_subfolders_still_installs(tmp_path: Path) -> None:
    source = _make_plugin(tmp_path)
    module = source / "pkg" / "deeper" / "module.py"
    module.parent.mkdir(parents=True)
    module.write_text("VALUE = 42\n", encoding="utf-8")
    install_root = tmp_path / "installed"

    result = install_plugin_from_local_path(
        PluginInstallFromLocalPathRequest(source_path=source, install_root=install_root)
    )

    assert result.plugin_name == "demo_plugin"
    assert (result.installed_path / "pkg" / "deeper" / "module.py").read_text(encoding="utf-8") == "VALUE = 42\n"
    assert (result.installed_path / "README.md").read_text(encoding="utf-8") == "hello"
