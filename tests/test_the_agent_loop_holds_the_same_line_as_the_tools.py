"""The agent loop judges a path before any tool runs, and holds the same line the tools hold.

``tests/test_code_tools_stay_inside_their_root.py`` holds the tools. These two are the ones the loop can break on its
own: it compared with ``os.path.commonpath``, which reads a Kelvin sign as ``k``, and it resolved a path before refusing
it, which opens a network path to find out it is outside.
"""

from __future__ import annotations

import ntpath
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from thomas.agent.loop_tool_paths import _validate_filesystem_path

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows path rules")

KELVIN = "\u212a"
HOST = "thomas-spy.invalid"


@pytest.mark.parametrize("name", ["work", "Desktop/proj"], ids=["the root's own name", "a folder above the root"])
def test_the_loop_does_not_take_a_twin_for_the_root(name: str, tmp_path: Path) -> None:
    root = tmp_path / name
    twin = tmp_path / name.replace("k", KELVIN)
    root.mkdir(parents=True)
    twin.mkdir(parents=True)
    (root / "inside.py").write_text("", encoding="utf-8")
    (twin / "leak.py").write_text("", encoding="utf-8")
    if os.path.samefile(root, twin):
        pytest.skip("This disk folds the Kelvin sign, so these are not two folders")

    checked, error = _validate_filesystem_path(str(twin / "leak.py"), sandbox_root=root)
    assert checked is None
    assert "outside the sandbox root" in str(error)

    checked, error = _validate_filesystem_path(str(root / "inside.py"), sandbox_root=root)
    assert error is None
    assert checked is not None


@pytest.fixture(params=["work", "Desktop/proj"], ids=["the root's own name", "a folder above the root"])
def benchmark_twins(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / request.param
    twin = tmp_path / request.param.replace("k", KELVIN)
    (root / "run").mkdir(parents=True)
    twin.mkdir(parents=True)
    if os.path.samefile(root, twin):
        pytest.skip("This disk folds the Kelvin sign, so these are not two folders")
    return root, twin


def test_a_benchmark_run_does_not_take_a_twin_for_its_root(benchmark_twins: tuple[Path, Path]) -> None:
    root, twin = benchmark_twins
    checked, error = _validate_filesystem_path(str(twin / "leak.py"), sandbox_root=root, benchmark_root=root)
    assert checked is None
    assert error == "absolute path is outside the benchmark root"
    checked, error = _validate_filesystem_path(str(root / "run" / "ok.py"), sandbox_root=root, benchmark_root=root)
    assert error is None
    assert checked is not None


def test_a_relative_path_in_a_benchmark_run_does_not_land_in_a_twin(benchmark_twins: tuple[Path, Path]) -> None:
    root, twin = benchmark_twins
    # A sandbox that sits in the twin is the only way a relative path gets there: ".." is refused before this check.
    checked, error = _validate_filesystem_path("leak.py", sandbox_root=twin, benchmark_root=root)
    assert checked is None
    assert error == "path is outside the benchmark root"
    checked, error = _validate_filesystem_path("ok.py", sandbox_root=root / "run", benchmark_root=root)
    assert (checked, error) == ("ok.py", None)


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What tried to touch the fake host. The real call never runs, so nothing here can reach a network."""
    touched: list[str] = []

    def guard(owner: Any, name: str) -> None:
        real = getattr(owner, name)

        def spy(path: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(path, (str, os.PathLike)) and HOST in os.fspath(path):
                touched.append(f"{name}({os.fspath(path)})")
                raise FileNotFoundError(2, "stopped by the test", os.fspath(path))
            return real(path, *args, **kwargs)

        monkeypatch.setattr(owner, name, spy)

    guard(ntpath, "_getfinalpathname")
    for name in ("stat", "lstat", "readlink", "scandir"):
        guard(os, name)
    return touched


@windows_only
@pytest.mark.parametrize(
    "path",
    [
        pytest.param(rf"\\{HOST}\share\x", id="a share"),
        pytest.param(f"//{HOST}/share/x", id="forward slashes"),
        pytest.param(rf"/\{HOST}\share\x", id="mixed slashes"),
        pytest.param(rf"\\\{HOST}\share\x", id="three slashes"),
        pytest.param(rf"\\?\UNC\{HOST}\share\x", id="verbatim"),
        pytest.param(rf"\\.\UNC\{HOST}\share\x", id="device"),
        pytest.param(rf"\??\UNC\{HOST}\share\x", id="native"),
        pytest.param(rf"\\{HOST}", id="no share"),
    ],
)
def test_the_loop_refuses_a_network_path_before_opening_it(path: str, tmp_path: Path, opened: list[str]) -> None:
    checked, error = _validate_filesystem_path(path, sandbox_root=tmp_path)
    assert checked is None
    assert "outside the sandbox root" in str(error)
    assert opened == []
