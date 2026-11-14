"""build_windows_installer.ps1 hands Inno Setup the staged bundle, and tidies up after it.

The script's hand-off to ISCC.exe is the heart of the installer fix: the installer must
compile the staged release bundle, never the folder above it. Inno Setup is not installed
on most machines, so these runs point ``ISCC_PATH`` (which the script honours) at a stub
that records what it was given and whether the bundle was complete at that moment.
Each run stages the real bundle, so each takes about half a minute.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "scripts" / "build_windows_installer.ps1"
OUT = ROOT / "dist" / "installer"
ISS = (ROOT / "installer" / "ThomasSetup.iss").read_text(encoding="utf-8")
GUIDE = (ROOT / "docs" / "WINDOWS_INSTALLER_GUIDE.md").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(
    os.name != "nt" or shutil.which("git") is None, reason="a PowerShell build of git files"
)

# What the installer's shortcuts and the first launch need from the bundle.
NEEDED = ("launch-thomas.vbs", "assets\\thomas.ico", "scripts\\startup_recovery_watch.ps1")

# cmd splits an argument at "=", so the stub is a Python script and ISCC_PATH is a .cmd that
# passes every argument on unchanged. It logs what it was given and whether each needed file
# was in the staged bundle at that moment.
STUB_PY = (
    f"NEEDED = {NEEDED!r}\n"
    + r"""import os
import sys
from pathlib import Path

args = sys.argv[1:]
stage = next((a[len("/DStageDir=") :] for a in args if a.startswith("/DStageDir=")), "")
lines = ["arg=" + a for a in args]
for needed in NEEDED:
    lines.append(("present=" if (Path(stage) / needed).exists() else "missing=") + needed)
with open(os.environ["ISCC_STUB_LOG"], "a", encoding="utf-8") as log:
    log.write("\n".join(lines) + "\n")
sys.exit(int(os.environ["ISCC_STUB_EXIT"]))
"""
)


@contextlib.contextmanager
def _tidy(version: str):
    """Leave dist/installer as it was found: a maintainer's own build may live there."""
    leave = [d for d in (OUT, OUT.parent) if d.exists()]
    try:
        yield OUT / f"Thomas_source_{version}"
    finally:
        (OUT / f"Thomas_source_{version}.zip").unlink(missing_ok=True)
        shutil.rmtree(OUT / f"Thomas_source_{version}", ignore_errors=True)
        for folder in (OUT, OUT.parent):
            if folder not in leave:
                with contextlib.suppress(OSError):
                    folder.rmdir()  # something else is in it; leave it


def _build(
    tmp_path: Path, version: str, iscc: Path, exit_code: int = 0
) -> tuple[subprocess.CompletedProcess, list[tuple[str, str]]]:
    log = tmp_path / "iscc.log"
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env.update(ISCC_PATH=str(iscc), ISCC_STUB_LOG=str(log), ISCC_STUB_EXIT=str(exit_code))
    command = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(BUILD)]
    done = subprocess.run(
        command + ["-Version", version],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    text = log.read_text(encoding="utf-8") if log.exists() else ""
    return done, [tuple(line.split("=", 1)) for line in text.splitlines() if "=" in line]


def _stub(tmp_path: Path) -> Path:
    script = tmp_path / "iscc_stub.py"
    script.write_text(STUB_PY, encoding="utf-8")
    stub = tmp_path / "iscc_stub.cmd"
    stub.write_bytes(f'@"{sys.executable}" "{script}" %*\r\n'.encode())
    return stub


def test_inno_gets_the_version_and_a_complete_staged_bundle_and_the_stage_is_removed_after(tmp_path: Path) -> None:
    version = "0.0.0-test-iscc"
    with _tidy(version) as stage:
        done, record = _build(tmp_path, version, _stub(tmp_path))
        assert done.returncode == 0, done.stdout + done.stderr
        kept = stage.exists()
    args = [value for key, value in record if key == "arg"]
    assert len(args) == 3, args
    assert args[0] == f"/DMyAppVersion={version}"
    assert args[1].startswith("/DStageDir=")
    assert args[1][11:].lower().endswith(f"dist\\installer\\thomas_source_{version}".lower()), (
        "Inno must compile the staged bundle, not the folder above it: " + args[1]
    )
    assert args[2].lower().endswith("installer\\thomassetup.iss")
    assert [v for k, v in record if k == "missing"] == [], "the bundle was incomplete when Inno was called"
    assert sorted(v for k, v in record if k == "present") == sorted(NEEDED), "no bundle when Inno was called"
    assert not kept, "the staged copy is thrown away once the installer is built"


def test_a_failed_compile_keeps_the_stage_for_inspection(tmp_path: Path) -> None:
    version = "0.0.0-test-iscc-fail"
    with _tidy(version) as stage:
        done, record = _build(tmp_path, version, _stub(tmp_path), exit_code=1)
        assert done.returncode != 0, "a failed ISCC run must fail the build"
        assert "ISCC compile failed" in done.stdout + done.stderr
        assert (stage / "launch-thomas.vbs").is_file(), "the stage is what the maintainer needs to debug the failure"
    assert ("arg", f"/DMyAppVersion={version}") in record


def test_no_inno_setup_stops_the_build_and_removes_the_stage(tmp_path: Path) -> None:
    defaults = [
        Path(os.environ.get(var, "C:\\nowhere")) / "Inno Setup 6" / "ISCC.exe"
        for var in ("ProgramFiles(x86)", "ProgramFiles")
    ] + [Path(os.environ.get("LOCALAPPDATA", "C:\\nowhere")) / "Programs" / "Inno Setup 6" / "ISCC.exe"]
    if any(path.exists() for path in defaults):
        pytest.skip("Inno Setup is installed here, so the script would find it")
    version = "0.0.0-test-iscc-none"
    with _tidy(version) as stage:
        done, record = _build(tmp_path, version, tmp_path / "no_such_iscc.cmd")
        kept = stage.exists()
    assert done.returncode == 2, done.stdout + done.stderr
    assert "ISCC.exe not found" in done.stdout
    assert not record, "nothing was compiled"
    assert not kept, "the staged copy is thrown away when there is nothing to compile it with"


def test_the_finish_page_and_the_guide_say_what_the_first_launch_installs() -> None:
    run_ui = (ROOT / "scripts" / "run-ui.ps1").read_text(encoding="utf-8")
    # The arguments the first launch always gives setup.ps1. -AutoInstallTools is added to them only on
    # -InstallTools or THOMAS_AUTO_INSTALL_TOOLS=1, so on its own the first launch installs no tools.
    call = re.search(r"\$setupArgs = @\(([^)\r\n]*\$setupScript[^)\r\n]*)\)", run_ui)
    assert call, "run-ui.ps1 no longer runs setup.ps1 at first launch; update the label and the guide"
    installs_tools = "-AutoInstallTools" in call.group(1)
    label = re.search(r'^Filename: "\{app\}\\\{#MyAppLauncherName\}"; Description: "([^"]+)"', ISS, re.MULTILINE)
    assert label, "the 'Launch Thomas now' entry lost its label"
    # The label and the guide say so exactly when it is true, so they cannot go stale either way.
    assert all(tool in label.group(1) for tool in ("Node.js", "Codex", "Ollama")) == installs_tools
    assert ("automatic tool installs turned on" in GUIDE) == installs_tools
