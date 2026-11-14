"""The documented installs leave a machine that can run ``thomas serve``.

install.cmd and install.sh ran a bare ``pip install .``. The web server's
dependencies (aiohttp, fastapi, pydantic, ...) are the ``server`` extra only, so a
clean install stopped at ``thomas serve`` with "Server dependencies missing" even
though both scripts closed by advertising the web UI. install.sh also advertised
``curl ... | bash``, which cannot work because the script installs the checkout it
sits in, and DEPLOYMENT.md called the compose stack locked down while the compose
file mounts the development config.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent

# A `pip install` of the project itself ("." or -e "."), with or without extras.
_PROJECT_INSTALL = re.compile(r'-m pip install (?:-e )?"?\.(?:\[([^\]"]*)\])?"?(?:\s|$)')


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _project_installs(name: str) -> list[set[str]]:
    """The extras each project install line in *name* asks for."""
    found = []
    for line in _read(name).splitlines():
        if line.strip().lower().startswith(("rem ", "#")):
            continue
        match = _PROJECT_INSTALL.search(line)
        if match:
            found.append({e.strip() for e in (match.group(1) or "").split(",") if e.strip()})
    return found


@pytest.mark.parametrize("script", ["install.cmd", "install.sh"])
def test_the_install_scripts_install_the_server_extra(script: str) -> None:
    installs = _project_installs(script)
    assert installs, f"{script} no longer installs the project; update this test with it"
    for extras in installs:
        assert "server" in extras, f"{script} installs the project without the server extra: {sorted(extras)}"


def test_the_extras_the_install_scripts_ask_for_exist() -> None:
    declared = set(tomllib.loads(_read("pyproject.toml"))["project"]["optional-dependencies"])
    asked = {
        extra for script in ("install.cmd", "install.sh") for extras in _project_installs(script) for extra in extras
    }
    assert asked <= declared, f"install scripts name extras pyproject does not declare: {sorted(asked - declared)}"


def test_the_server_extra_carries_what_thomas_serve_imports() -> None:
    server = tomllib.loads(_read("pyproject.toml"))["project"]["optional-dependencies"]["server"]
    assert any(req.lower().startswith("aiohttp") for req in server), server


def test_both_install_scripts_can_install_editable_the_way_run_ui_does() -> None:
    # What install.cmd does with the switch, and in which order, is read in
    # test_a_windows_install_uses_the_venv_and_stops_on_a_bad_python.py.
    for script in ("install.cmd", "install.sh"):
        assert "THOMAS_DEV" in _read(script), f"{script} has no way to ask for an editable install"
        lines = [
            line
            for line in _read(script).splitlines()
            if "-m pip install" in line and not line.strip().lower().startswith(("rem ", "#"))
        ]
        assert any("-e " in line for line in lines), f"{script} never installs editable"
        assert any("-e " not in line for line in lines), f"{script} always installs editable"


def test_the_install_scripts_stop_at_the_pythons_pyproject_lists() -> None:
    """Thomas pins numpy 2.2.6, which has no prebuilt package for a newer Python, so a
    stranger with the latest Python used to reach pip and fail inside a source build."""
    classifiers = tomllib.loads(_read("pyproject.toml"))["project"]["classifiers"]
    listed = sorted(
        int(m.group(1)) for c in classifiers if (m := re.fullmatch(r"Programming Language :: Python :: 3\.(\d+)", c))
    )
    low, high = listed[0], listed[-1]
    assert f"(3, {low}) <= sys.version_info[:2] <= (3, {high})" in _read("install.cmd")
    sh = _read("install.sh")
    assert f'"$minor" -ge {low}' in sh and f'"$minor" -le {high}' in sh
    # A default python3 newer than the range must not hide a supported one installed beside it.
    tried = [f"python3.{minor}" for minor in range(high, low - 1, -1)] + ["python3", "python"]
    assert f"for cmd in {' '.join(tried)}; do" in sh, "install.sh must try each supported python3.N, newest first"
    for script in ("install.cmd", "install.sh"):
        assert f"3.{low} to 3.{high}" in _read(script), f"{script} must name the range it accepts"


def test_install_sh_does_not_advertise_a_curl_pipe() -> None:
    lines = _read("install.sh").splitlines()
    header = "\n".join(line for line in lines[:16] if line.startswith("#"))
    assert not re.search(r"curl\b[^\n]*\|\s*(?:ba)?sh", header), header
    for line in lines:
        if "BASH_SOURCE[0]" in line:
            assert "BASH_SOURCE[0]:-" in line, f"unbound under set -u when piped: {line.strip()}"


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _working_bash() -> str | None:
    bash = shutil.which("bash")
    if not bash:
        return None
    try:
        probe = subprocess.run(
            [bash, "-c", "echo ok"], capture_output=True, text=True, timeout=45, creationflags=_NO_WINDOW
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return bash if probe.stdout.strip() == "ok" else None


def test_piping_install_sh_stops_with_the_real_reason(tmp_path: Path) -> None:
    bash = _working_bash()
    if bash is None:
        pytest.skip("no working bash on this machine")
    # LF only: a Windows checkout may hold CRLF, which bash reads as part of each line.
    script = (ROOT / "install.sh").read_bytes().replace(b"\r\n", b"\n")
    # With THOMAS_INSTALL_DIR pointing at a real checkout the script would get past the
    # pyproject check and really create a .venv and run pip there.
    env = {k: v for k, v in os.environ.items() if k not in ("THOMAS_INSTALL_DIR", "THOMAS_NO_VENV", "THOMAS_DEV")}
    try:
        done = subprocess.run(
            [bash, "-s"], input=script, cwd=tmp_path, env=env, capture_output=True, timeout=90, creationflags=_NO_WINDOW
        )
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("bash could not run the script here")
    output = (done.stdout + done.stderr).decode("utf-8", "replace")
    if "is required but not found" in output:
        pytest.skip("this bash has no Python 3.10 to 3.13, which install.sh checks before it looks for the project")
    assert done.returncode != 0
    assert "unbound variable" not in output, output
    assert "Cannot find pyproject.toml" in output, output


def test_install_sh_offers_to_start_the_ui_and_onboarding_says_so() -> None:
    script = _read("install.sh")
    assert 'exec "$PYTHON" -m thomas serve' in script
    assert "Start Thomas now?" in script
    onboarding = _read("ONBOARDING.md")
    section = onboarding.split("### macOS / Linux", 1)[1].split("###", 1)[0]
    assert "offers to start" in section, "ONBOARDING should say install.sh only offers to start the UI"


def test_deployment_quick_start_activates_the_environment_before_serving() -> None:
    text = _read("DEPLOYMENT.md")
    block = text.split("### Development (local)", 1)[1].split("```bash", 1)[1].split("```", 1)[0]
    assert "install.sh" in block
    assert "activate" in block, "install.sh activates its venv only for itself; the reader must do it"
    assert block.index("activate") < block.index("python -m thomas serve")
    assert "python -m thomas.server" not in block
    # install.sh asks before it creates the .venv, so the activate line cannot be unconditional.
    assert "asks whether to" in block and "declined" in block, "say the .venv is optional"
    onboarding = _read("ONBOARDING.md").split("### macOS / Linux", 1)[1].split("###", 1)[0]
    assert "offers to create a virtual environment" in onboarding
    assert "creates `.venv`" not in _read("README.md")


def test_deployment_describes_the_config_the_compose_stack_really_uses() -> None:
    compose = _read("docker-compose.yml")
    deployment = _read("DEPLOYMENT.md")
    uses_dev_config = "THOMAS_CONFIG: /app/thomas.toml" in compose
    if uses_dev_config:
        assert "locked-down defaults" not in deployment, "compose mounts the development thomas.toml"
    # The guide says so exactly when it is true, so it cannot go stale in either direction.
    assert uses_dev_config == ("sets `THOMAS_CONFIG` to the development" in deployment)
