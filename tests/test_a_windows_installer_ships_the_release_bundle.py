"""The Windows installer ships the release bundle, not the machine it was built on.

ThomasSetup.iss read the repository's working tree (``Source: "..\\*"``) and its
Excludes list was separated by semicolons. Inno Setup separates patterns with commas,
so the whole string was one pattern that matched nothing: an installer built on a
maintainer's machine carried their .venv, runtime state, .env.local and untracked
files. Fixing only the separator would have made it worse, because the bare
``runtime\\*`` pattern matches from the end of a path and would also drop the product's
own thomas/server/web/js/runtime/ scripts.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ISS = (ROOT / "installer" / "ThomasSetup.iss").read_text(encoding="utf-8")
BUILD = (ROOT / "scripts" / "build_windows_installer.ps1").read_text(encoding="utf-8")
GUIDE = (ROOT / "docs" / "WINDOWS_INSTALLER_GUIDE.md").read_text(encoding="utf-8")


def _packager():
    spec = importlib.util.spec_from_file_location("_pkg_release", ROOT / "scripts" / "package_release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundle_paths() -> set[str]:
    module = _packager()
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False).stdout
    return {p for p in tracked.splitlines() if p.strip() and module._is_excluded(p.strip()) is None}


def _excludes() -> list[str]:
    match = re.search(r'^Source: "\{#StageDir\}\\\*";.*?Excludes: "([^"]*)"', ISS, re.MULTILINE)
    assert match, "the [Files] entry must read the staged bundle and carry an Excludes list"
    return match.group(1).split(",")


def _inno_excludes(relative: str, patterns: list[str]) -> bool:
    """Inno Setup's rule: a leading backslash anchors at the start, otherwise at the end."""
    path = "\\" + relative.replace("/", "\\")
    for pattern in patterns:
        wanted = pattern if pattern.startswith("\\") else "*\\" + pattern
        if fnmatch.fnmatchcase(path.lower(), wanted.lower()):
            return True
    return False


def _section(name: str) -> str:
    return ISS.split(f"[{name}]", 1)[1].split("\n[", 1)[0]


def _own_lines() -> dict[str, str]:
    """[Files] entries that take one named file from the bundle, with their flags."""
    pattern = r'^Source: "\{#StageDir\}\\([^*"]+)";.*?Flags: ([^;\n]+)'
    return {name.replace("\\", "/"): flags for name, flags in re.findall(pattern, _section("Files"), re.MULTILINE)}


# Scripts a launcher only reaches behind an opt-in switch or an existence check, so a
# bundle without them still starts.
OPTIONAL_SCRIPTS = {
    "scripts/watch_monolith_guard.py",  # run-ui.ps1, only when THOMAS_MONOLITH_WATCH is set
    "scripts/thomas_app.py",  # setup.ps1 tests for it first; it builds on desktop/, which does not ship
}
LAUNCHERS = (
    "run-ui.cmd",
    "repair.cmd",
    "setup.cmd",
    "run-repl.cmd",
    "bootdoctor.cmd",
    "launch-thomas.vbs",
    "scripts/run-ui.ps1",
    "scripts/setup.ps1",
    "scripts/repair.ps1",
    "scripts/bootdoctor.ps1",
    "scripts/run-repl.ps1",
)


def _scripts_named_by_the_launchers() -> set[str]:
    named: set[str] = set()
    for launcher in LAUNCHERS:
        text = (ROOT / launcher).read_text(encoding="utf-8")
        named |= {"scripts/" + name for name in re.findall(r"scripts[\\/]+([\w.-]+\.(?:ps1|py))", text)}
    return named


def test_the_installer_compiles_from_the_staged_bundle_only() -> None:
    assert 'Source: "..\\*"' not in ISS, "the working tree must never be the source"
    assert re.search(r"#ifndef StageDir\s+#error", ISS), "compiling without a staged bundle must stop"
    assert re.search(r"#ifndef MyAppVersion\s+#error", ISS), "an unversioned installer must not be built"


def test_the_build_script_stages_from_git_not_the_working_tree() -> None:
    assert "scripts\\package_release.py" in BUILD
    assert "/DStageDir=" in BUILD
    assert "robocopy" not in BUILD, "robocopy copies the working tree, untracked files included"
    assert "Compress-Archive" not in BUILD, "it flattened every file into the zip root"


def test_the_build_script_needs_no_version_argument() -> None:
    assert re.search(r'\[string\]\$Version = ""', BUILD)
    pattern = re.search(r"\$VersionPattern = '([^']+)'", BUILD)
    assert pattern, "the script must name the pattern it reads the version with"
    version = re.search(pattern.group(1), (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert version, "the pattern must match pyproject.toml"
    init = re.search(r'^__version__ = "([^"]+)"', (ROOT / "thomas" / "__init__.py").read_text(encoding="utf-8"), re.M)
    assert init and version.group(1) == init.group(1)
    assert "0.0.0-dev" not in BUILD + ISS
    assert "-Version 0.1.0" not in GUIDE


def test_the_excludes_are_comma_separated() -> None:
    patterns = _excludes()
    assert len(patterns) > 3
    assert not [p for p in patterns if ";" in p], "a semicolon is part of one pattern, not a separator"


def test_the_excludes_keep_out_local_state_and_drop_nothing_the_bundle_ships() -> None:
    patterns = _excludes()
    for local in (".git\\config", ".venv\\pyvenv.cfg", ".thomas\\state.json", "runtime\\run.json", ".env.local"):
        assert _inno_excludes(local, patterns), f"{local} would be shipped"
    assert _inno_excludes("thomas/core/__pycache__/x.pyc", patterns)
    shipped = _bundle_paths()
    assert any("/runtime/" in p for p in shipped), "expected the web runtime scripts in the bundle"
    # Files with a [Files] line of their own are taken out of the wildcard line on purpose.
    dropped = sorted(p for p in shipped if _inno_excludes(p, patterns) and p not in _own_lines())
    assert not dropped, f"Excludes would remove shipped files: {dropped[:5]}"


def test_every_file_the_installer_points_at_is_in_the_bundle() -> None:
    names = dict(re.findall(r'^#define (\w+) "([^"]*)"', ISS, re.MULTILINE))
    scanned = "\n".join(_section(s) for s in ("Setup", "Icons", "Run"))
    # MyAppVersion and StageDir come from the command line, not from a #define.
    scanned = re.sub(r"\{#(\w+)\}", lambda m: names.get(m.group(1), m.group(1)), scanned)
    targets = {m.replace("\\", "/") for m in re.findall(r"\{app\}\\([\w.\\-]+)", scanned)}
    assert {"launch-thomas.vbs", "run-ui.cmd", "repair.cmd", "assets/thomas.ico"} <= targets, targets
    missing = sorted(targets - _bundle_paths())
    assert not missing, f"the installer points at files the bundle does not ship: {missing}"


def test_every_script_the_launchers_call_is_in_the_bundle() -> None:
    named = _scripts_named_by_the_launchers()
    assert "scripts/startup_recovery_watch.ps1" in named, "the scan found nothing; check the pattern"
    assert named >= OPTIONAL_SCRIPTS, "an optional script is no longer named by a launcher; drop it from the list"
    missing = sorted(named - OPTIONAL_SCRIPTS - _bundle_paths())
    assert not missing, f"a launcher calls scripts the installed copy would not have: {missing}"


def test_the_finish_page_hands_the_launcher_script_to_the_shell() -> None:
    names = dict(re.findall(r'^#define (\w+) "([^"]*)"', ISS, re.MULTILINE))
    entries = [line for line in _section("Run").splitlines() if line.startswith("Filename:")]
    assert any("postinstall" in line for line in entries), "expected the 'Launch Thomas now' entry"
    for line in entries:
        line = re.sub(r"\{#(\w+)\}", lambda m: names.get(m.group(1), m.group(1)), line)
        target = re.match(r'Filename: "([^"]+)"', line).group(1)
        flags = re.search(r"Flags: ([^;]+)", line).group(1).split()
        if not target.lower().endswith((".exe", ".com")):
            assert "shellexec" in flags, f"Inno starts {target} with CreateProcess, which fails on a script: {line}"


def test_an_upgrade_keeps_the_thomas_toml_setup_wrote_and_the_manifest_stays_out() -> None:
    patterns = _excludes()
    assert _inno_excludes("thomas.toml", patterns), "the wildcard line would overwrite thomas.toml on an upgrade"
    assert _inno_excludes("RELEASE_MANIFEST.json", patterns), "nothing reads the manifest at run time"
    assert "onlyifdoesntexist" in _own_lines()["thomas.toml"].split()
    setup = (ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8")
    assert "Set-DefaultModelName" in setup and "thomas.toml" in setup, "setup no longer writes thomas.toml"


def test_the_spike_and_machine_files_cannot_ship() -> None:
    module = _packager()
    assert "package_release.py" in BUILD, "the build must stage through the allow-list"
    for name in (
        "desktop/spike.js",
        "desktop/spike_bridge.py",
        "desktop/spike-results.json",
        "desktop/spike_err.log",
        "desktop/boot.log",
        "desktop/bridge.json",
        "desktop/wellsfargo.png",
        "Thomas.vbs",
        ".env.local",
        ".thomas/state.json",
        "runtime/run.json",
    ):
        assert module._is_excluded(name) is not None, f"{name} would ship"


def test_the_shortcuts_carry_the_app_icon_and_the_uninstaller_clears_the_venv() -> None:
    shortcuts = [
        line for line in _section("Icons").splitlines() if line.startswith("Name:") and "{uninstallexe}" not in line
    ]
    assert len(shortcuts) == 6, shortcuts  # Thomas, Console, Repair, Stop, Restart and the desktop icon
    for line in shortcuts:
        assert 'IconFilename: "{app}\\assets\\thomas.ico"' in line, line
    assert "UninstallDisplayIcon={app}\\assets\\thomas.ico" in ISS
    assert 'Name: "{app}\\.venv"' in _section("UninstallDelete")


def test_the_support_links_point_at_the_project_not_at_the_local_server() -> None:
    urls = re.findall(r"^App(?:Publisher|Support|Updates)URL=(.*)$", ISS, re.MULTILINE)
    assert len(urls) == 3
    resolved = [u.replace("{#MyAppURL}", re.search(r'#define MyAppURL "([^"]+)"', ISS).group(1)) for u in urls]
    assert all(u.startswith("https://") and "127.0.0.1" not in u for u in resolved), resolved


def test_the_guide_names_the_inno_release_the_script_needs() -> None:
    assert "6.3" in GUIDE and "#if VER < EncodeVer(6, 3, 0, 0)" in ISS
    assert "x64compatible" in ISS


@pytest.mark.skipif(os.name != "nt", reason="PowerShell's own parser")
def test_the_build_script_parses() -> None:
    script = ROOT / "scripts" / "build_windows_installer.ps1"
    parse = (
        "$tokens = $null; $errors = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$tokens, [ref]$errors) "
        "| Out-Null; $errors | ForEach-Object { $_.Message }; 'errors:' + $errors.Count"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", parse],
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert out.stdout.strip().endswith("errors:0"), out.stdout + out.stderr


@pytest.mark.skipif(os.name != "nt", reason="the build script is PowerShell")
def test_the_build_script_makes_a_bundle_that_can_start_and_names_nothing_private() -> None:
    """Runs the real script (about 30 s): the source checks above cannot see what it stages."""
    if shutil.which("git") is None:
        pytest.skip("the build stages tracked files with git")
    version = "0.0.0-test"
    out_dir = ROOT / "dist" / "installer"
    leave = [d for d in (out_dir, out_dir.parent) if d.exists()]
    zip_path = out_dir / f"Thomas_source_{version}.zip"
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
            + [str(ROOT / "scripts" / "build_windows_installer.ps1"), "-SkipCompile", "-Version", version],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert done.returncode == 0, done.stdout + done.stderr
        with zipfile.ZipFile(zip_path) as bundle:
            names = set(bundle.namelist())
            texts = {n: bundle.read(n).decode("utf-8", "replace") for n in names if n.startswith("RELEASE_")}
            notices = bundle.read("THIRD_PARTY_NOTICES.md").decode("utf-8", "replace")
            install_sh = bundle.read("install.sh")
    finally:
        zip_path.unlink(missing_ok=True)
        shutil.rmtree(out_dir / f"Thomas_source_{version}", ignore_errors=True)
        for folder in (out_dir, out_dir.parent):
            if folder not in leave:
                try:
                    folder.rmdir()
                except OSError:
                    pass  # something else is in it; leave it
    for needed in ("launch-thomas.vbs", "run-ui.cmd", "assets/thomas.ico", "scripts/run-ui.ps1"):
        assert needed in names, f"the zip cannot start without {needed}"
    assert "scripts/startup_recovery_watch.ps1" in names
    assert b"\r" not in install_sh, "bash on macOS or Linux stops at the carriage return of a CRLF checkout"
    for local in ("Thomas.vbs", ".env.local"):
        assert local not in names
    leaked = sorted(n for n in names if n.startswith((".venv/", "runtime/", ".thomas/", "plans/", "tests/")))
    assert not leaked, f"the zip carries the build machine's state: {leaked[:5]}"
    manifest = texts["RELEASE_MANIFEST.json"]
    summary = texts["RELEASE_SUMMARY.md"]
    for text in (manifest, summary, notices):
        for build_path in (str(ROOT), str(ROOT).replace("\\", "\\\\"), str(ROOT).replace("\\", "/")):
            assert build_path not in text, "a shipped file names the folder it was built in"
        assert '"plans/' not in text and '"tests/' not in text and "scripts/crew" not in text
    assert "excluded" not in json.loads(manifest), "the manifest must not list what was left out"
    assert len(notices.splitlines()) > 5 and len(summary.splitlines()) > 5, "written with literal backslash-n"
