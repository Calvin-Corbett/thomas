"""Engine checks are chosen by what each changed file is (harness report item 4, K3).

Before: any changed path under ``tests/`` went to pytest, so ``tests/app.test.js`` failed with pytest's exit 4 every
fix pass, and ``app.js`` beside it was never syntax-checked. A file no allowed runner can run is UNCHECKED, never a
failure.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from thomas.forge.anvil import build_verify
from thomas.forge.anvil.verify_routing import route_changed_files

NODE_TEST = "const test = require('node:test');\nconst app = require('../app.js');\ntest('ok', () => { void app; });\n"


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


def _recording():
    cmds: list[list[str]] = []

    def run_check(cmd, cwd, timeout):
        cmds.append(list(cmd))
        return 0, "ok"

    return cmds, run_check


def test_a_js_test_is_never_handed_to_pytest(tmp_path: Path) -> None:
    _write(tmp_path, "app.js", "const a = 1;\n")
    _write(tmp_path, "tests/app.test.js", NODE_TEST)
    cmds, run_check = _recording()
    ok, rc, _ = build_verify.verify_python_changes(
        tmp_path, ["app.js", "tests/app.test.js"], lambda _e: None, run_check=run_check
    )
    assert (ok, rc) == (True, 0)
    assert not any("pytest" in c for cmd in cmds for c in cmd), cmds
    # app.js is checked by the static program, not skipped.
    assert any("app.js" in " ".join(cmd) and "-c" in cmd for cmd in cmds), cmds


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_node_test_file_runs_with_node_test(tmp_path: Path) -> None:
    _write(tmp_path, "tests/app.test.js", NODE_TEST)
    routing = route_changed_files(tmp_path, ["tests/app.test.js"])
    assert routing.node_tests == ["tests/app.test.js"]
    cmds, run_check = _recording()
    build_verify.verify_python_changes(tmp_path, ["tests/app.test.js"], lambda _e: None, run_check=run_check)
    assert any(cmd[1:3] == ["--test", "tests/app.test.js"] for cmd in cmds), cmds


def test_a_python_test_still_goes_to_pytest_and_other_python_is_compiled(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_x.py", "def test_x():\n    pass\n")
    _write(tmp_path, "tests/helpers.py", "X = 1\n")
    routing = route_changed_files(tmp_path, ["tests/test_x.py", "tests/helpers.py"])
    assert routing.python_tests == ["tests/test_x.py"]
    assert routing.static == ["tests/helpers.py"]  # pytest on a helper collects nothing: a fake failure


def test_a_test_with_no_allowed_runner_is_unchecked_not_failed(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", json.dumps({"scripts": {"test": "jest"}}))
    _write(tmp_path, "tests/app.test.js", "test('x', () => {});\n")
    _write(tmp_path, "tests/app.test.ts", "export {};\n")
    events: list[dict] = []
    cmds, run_check = _recording()
    ok, rc, summary = build_verify.verify_python_changes(
        tmp_path, ["tests/app.test.js", "tests/app.test.ts"], events.append, run_check=run_check
    )
    assert (ok, rc) == (True, 0)
    assert "UNCHECKED" in summary and "jest" in summary
    assert not any("pytest" in c or "--test" in c for cmd in cmds for c in cmd), cmds
    assert any(e.get("text", "").startswith("UNCHECKED") and e.get("is_error") is False for e in events)


def test_the_real_check_of_a_js_test_does_not_fail_with_pytest_exit_4(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    _write(tmp_path, "app.js", "module.exports = 1;\n")
    _write(tmp_path, "tests/app.test.js", NODE_TEST)
    ok, rc, summary = build_verify.verify_python_changes(tmp_path, ["app.js", "tests/app.test.js"], lambda _e: None)
    assert (ok, rc) == (True, 0), summary


def test_bytecode_the_check_itself_wrote_is_not_failed_as_text(tmp_path: Path) -> None:
    """py_compile writes __pycache__; a second pass saw the .pyc as changed and failed it as non-UTF-8 text."""
    _write(tmp_path, "feature.py", "V = 1\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "feature.cpython-312.pyc").write_bytes(bytes([0xCB, 0x0D, 0x0D, 0x0A, 0, 0]))
    ok, rc, summary = build_verify.verify_python_changes(
        tmp_path, ["__pycache__/feature.cpython-312.pyc", "feature.py"], lambda _e: None
    )
    assert (ok, rc) == (True, 0), summary
    assert build_verify.verify_python_changes(tmp_path, ["__pycache__/feature.cpython-312.pyc"], lambda _e: None)[
        :2
    ] == (True, 0)
