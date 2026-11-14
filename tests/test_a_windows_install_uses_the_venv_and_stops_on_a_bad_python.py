"""install.cmd does what its messages say: it stops on a bad Python and installs into ``.venv``.

The script is never run here (it installs software), so this reads its structure: which
block each command sits in, in what order, and how each branch ends. A substring check
("the word venv appears") passed when the ``set PYTHON=`` line that points pip at the
venv was deleted, when the editable and copy branches were swapped, and when the Python
gate's ``exit /b 1`` became ``exit /b 0``.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent

VENV_PYTHON = "set PYTHON=.venv\\Scripts\\python.exe"
NO_VENV_HEADER = 'if not "%THOMAS_NO_VENV%"=="1" ('
DEV_HEADER = 'if "%THOMAS_DEV%"=="1" ('


def _code() -> list[str]:
    """Each command line of install.cmd, stripped, with comments and blanks dropped."""
    lines = [line.strip() for line in (ROOT / "install.cmd").read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln and not ln.lower().startswith(("rem ", "::")) and ln.lower() != "rem"]


def _block(lines: list[str], start: int) -> tuple[list[str], list[str]]:
    """The (then, else) lines of the parenthesised block whose opening line is lines[start]."""
    assert lines[start].endswith("("), lines[start]
    depth, side, parts = 1, 0, ([], [])
    for line in lines[start + 1 :]:
        if not line.lower().startswith("echo "):  # echo text is data, not structure
            if line == ")":
                depth -= 1
                if depth == 0:
                    return parts
            elif line.startswith(")") and line.endswith("("):
                if depth == 1:
                    side = 1
                    continue
            elif line.endswith("("):
                depth += 1
        parts[side].append(line)
    raise AssertionError(f"unclosed block: {lines[start]}")


def _at(lines: list[str], line: str) -> int:
    assert line in lines, f"install.cmd no longer has {line!r}; update this test with it"
    return lines.index(line)


def _pip_installs(lines: list[str]) -> list[str]:
    return [ln for ln in lines if "-m pip install" in ln]


def test_a_python_outside_the_supported_range_stops_the_install() -> None:
    code = _code()
    gate = next(i for i, ln in enumerate(code) if "sys.version_info" in ln)
    assert code[gate + 1] == "if errorlevel 1 (", "the version check is not followed by a branch on its result"
    then, _ = _block(code, gate + 1)
    assert "exit /b 1" in then, "an unsupported Python carries on to pip"
    assert "exit /b 0" not in then
    first_pip = next(i for i, ln in enumerate(code) if "-m pip install" in ln)
    assert gate < first_pip, "pip runs before the Python version is checked"
    assert gate < code.index("%PYTHON% -m venv .venv"), "the venv is built before the Python version is checked"


def test_no_failed_step_exits_with_success() -> None:
    code = _code()
    failed = [i for i, ln in enumerate(code) if ln == "if errorlevel 1 ("]
    assert len(failed) >= 4, "expected a check after the Python lookup, the gate, the venv and pip"
    for i in failed:
        then, _ = _block(code, i)
        assert "exit /b 1" in then, f"a failed step does not stop the install: {then}"
        assert "exit /b 0" not in then
    assert not [ln for ln in code if ln in ("exit /b 0", "exit 0")], "install.cmd exits with success early"


def test_thomas_goes_into_the_venv_and_not_into_the_global_python() -> None:
    code = _code()
    venv = _at(code, NO_VENV_HEADER)
    then, otherwise = _block(code, venv)
    assert not otherwise
    assert "%PYTHON% -m venv .venv" in then, "the venv is never created"
    assert VENV_PYTHON in then, "the venv is created and then ignored: pip would run in the global Python"
    assert then.index("%PYTHON% -m venv .venv") < then.index(VENV_PYTHON), "pip is pointed at a venv not yet built"
    assert code.count(VENV_PYTHON) == 1, "the venv interpreter must be chosen only when the venv is wanted"

    installs = _pip_installs(code)
    assert len(installs) == 2, installs
    assert all(ln.startswith("%PYTHON% -m pip install") for ln in installs), installs
    assert venv < code.index(installs[0]), "pip runs before the venv interpreter is chosen"
    setup = [ln for ln in code if "-m thomas setup" in ln]
    assert setup and all(ln.startswith("%PYTHON% ") for ln in setup), setup


def test_thomas_dev_picks_the_editable_install_and_nothing_else_does() -> None:
    code = _code()
    then, otherwise = _block(code, _at(code, DEV_HEADER))
    editable, copy = _pip_installs(then), _pip_installs(otherwise)
    assert len(editable) == 1 and " -e " in editable[0], f"THOMAS_DEV=1 does not install editable: {then}"
    assert len(copy) == 1 and " -e " not in copy[0], f"the default install is editable: {otherwise}"
    assert "[server,repl]" in editable[0] and "[server,repl]" in copy[0]


def test_a_venv_that_holds_an_editable_install_keeps_it() -> None:
    code = _code()
    venv_then, _ = _block(code, _at(code, NO_VENV_HEADER))
    detect = next((i for i, ln in enumerate(venv_then) if ln.startswith('if not "%THOMAS_DEV%"=="1" if exist ')), None)
    assert detect is not None, "a copy install would replace the editable install run-ui.cmd made"
    then, _ = _block(venv_then, detect)
    assert "set THOMAS_DEV=1" in then
    assert detect > venv_then.index(VENV_PYTHON), "the venv is checked before it is chosen"
    assert code.index(NO_VENV_HEADER) < code.index(DEV_HEADER), "the branch is taken before it is decided"

    # The pattern must match what pip writes for this project, and not a plain copy install.
    glob = re.search(r'if exist "([^"]+)"', venv_then[detect]).group(1)
    folder, _, pattern = glob.rpartition("\\")
    assert folder == ".venv\\Lib\\site-packages"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"]
    stem = project.replace("-", "_")
    for written in (f"__editable__.{stem}-0.19.41.pth", f"__editable___{stem}_0_19_41_finder.py"):
        assert fnmatch.fnmatchcase(written, pattern), f"{pattern} misses {written}, which pip writes"
    assert not fnmatch.fnmatchcase(f"{stem}-0.19.41.dist-info", pattern), "a copy install looks editable"


def test_no_echo_inside_a_block_closes_the_block_early() -> None:
    depth = 0
    for line in _code():
        if line.lower().startswith("echo "):
            assert depth == 0 or ")" not in line, f"this echo ends its block at the parenthesis: {line}"
        elif line == ")":
            depth -= 1
        elif line.endswith("("):
            depth += 0 if line.startswith(")") else 1
    assert depth == 0, "install.cmd has unbalanced parentheses"


def test_install_cmd_prints_plain_ascii() -> None:
    """cmd prints UTF-8 em dashes as garbage; the whole file stays ASCII."""
    data = (ROOT / "install.cmd").read_bytes()
    bad = sorted({hex(b) for b in data if b > 127})
    assert not bad, f"install.cmd holds non-ASCII bytes {bad}"
