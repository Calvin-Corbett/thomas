"""Desktop shortcut management for Thomas.

Creates platform-appropriate shortcuts to launch Thomas
from the desktop, start menu, or dock.
"""

from __future__ import annotations

import logging
import stat
import subprocess
import sys
from pathlib import Path

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

logger = logging.getLogger(__name__)


def _get_python_path() -> str:
    """Get the path to the Python executable."""
    return sys.executable or "python3"


def _get_platform() -> str:
    """Detect the current platform."""
    if sys.platform == "darwin":
        return "macos"
    elif sys.platform == "win32":
        return "windows"
    return "linux"


def _get_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _install_linux(mode: str) -> str | None:
    """Create a .desktop file on Linux.

    Args:
        mode: 'repl' or 'serve'

    Returns:
        Path to created shortcut
    """
    apps_dir = Path.home() / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)

    python = _get_python_path()
    if mode == "serve":
        cmd = f"{python} -m thomas serve"
        name = "Thomas AI (Web)"
        comment = "Launch Thomas web interface"
    else:
        cmd = f"{python} -m thomas repl"
        name = "Thomas AI (Terminal)"
        comment = "Launch Thomas interactive REPL"

    desktop_content = f"""[Desktop Entry]
Type=Application
Name={name}
Comment={comment}
Exec={cmd}
Terminal={'true' if mode == 'repl' else 'false'}
Categories=Development;Utility;
Keywords=AI;assistant;chat;
"""
    filename = f"thomas-{mode}.desktop"
    path = apps_dir / filename
    path.write_text(desktop_content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)

    logger.info("Created Linux desktop shortcut: %s", path)
    return str(path)


def _install_macos(mode: str) -> str | None:
    """Create a .command file on macOS.

    Args:
        mode: 'repl' or 'serve'

    Returns:
        Path to created shortcut
    """
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        desktop = Path.home()

    python = _get_python_path()
    if mode == "serve":
        script = f"#!/bin/bash\ncd ~\n{python} -m thomas serve\n"
        filename = "Thomas AI (Web).command"
    else:
        script = f"#!/bin/bash\ncd ~\n{python} -m thomas repl\n"
        filename = "Thomas AI (Terminal).command"

    path = desktop / filename
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)

    logger.info("Created macOS shortcut: %s", path)
    return str(path)


def _install_windows(mode: str) -> str | None:
    """Create a shortcut on Windows.

    Args:
        mode: 'repl' or 'serve'

    Returns:
        Path to created shortcut, or None on failure
    """
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        desktop = Path.home()

    repo_root = _get_repo_root()
    python = _get_python_path()
    launch_vbs = repo_root / "launch-thomas.vbs"

    if mode == "serve":
        shortcut_name = "Thomas AI.lnk"
        target_path = str(launch_vbs)
        arguments = ""
        working_directory = str(repo_root)
    else:
        shortcut_name = "Thomas AI Terminal.lnk"
        target_path = "powershell.exe"
        arguments = f"-NoExit -Command & '{python}' -m thomas repl"
        working_directory = str(repo_root)

    shortcut_path = desktop / shortcut_name
    ps_script = "\n".join(
        [
            "$shell = New-Object -ComObject WScript.Shell",
            f"$shortcut = $shell.CreateShortcut('{shortcut_path}')",
            f"$shortcut.TargetPath = '{target_path}'",
            f"$shortcut.Arguments = '{arguments}'",
            f"$shortcut.WorkingDirectory = '{working_directory}'",
            "$shortcut.Save()",
        ]
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        logger.warning("Failed to create Windows shortcut via PowerShell: %s", exc)
        return None

    if result.returncode != 0:
        logger.warning("PowerShell shortcut creation failed: %s", result.stderr.strip())
        return None

    logger.info("Created Windows shortcut: %s", shortcut_path)
    return str(shortcut_path)


def install_shortcuts(mode: str = "repl") -> list:
    """Install desktop shortcuts for the current platform.

    Args:
        mode: 'repl' or 'serve' or 'both'

    Returns:
        List of created shortcut paths
    """
    platform = _get_platform()
    modes = ["repl", "serve"] if mode == "both" else [mode]
    created = []

    installers = {
        "linux": _install_linux,
        "macos": _install_macos,
        "windows": _install_windows,
    }

    installer = installers.get(platform)
    if not installer:
        logger.warning("Unsupported platform: %s", platform)
        return []

    for m in modes:
        path = installer(m)
        if path:
            created.append(path)

    return created


def remove_shortcuts() -> list:
    """Remove Thomas desktop shortcuts.

    Returns:
        List of removed shortcut paths
    """
    removed = []
    platform = _get_platform()

    if platform == "linux":
        apps_dir = Path.home() / ".local" / "share" / "applications"
        for name in ["thomas-repl.desktop", "thomas-serve.desktop"]:
            p = apps_dir / name
            if p.exists():
                p.unlink()
                removed.append(str(p))

    elif platform == "macos":
        desktop = Path.home() / "Desktop"
        for name in ["Thomas AI (Web).command", "Thomas AI (Terminal).command"]:
            p = desktop / name
            if p.exists():
                p.unlink()
                removed.append(str(p))

    elif platform == "windows":
        desktop = Path.home() / "Desktop"
        for name in ["Thomas AI.lnk", "Thomas AI Terminal.lnk", "Thomas AI (Web).bat", "Thomas AI (Terminal).bat"]:
            p = desktop / name
            if p.exists():
                p.unlink()
                removed.append(str(p))

    return removed


def register_shortcuts_commands(cli: click.Group) -> None:
    """Register shortcuts commands with the CLI."""

    @cli.group("shortcuts")
    def shortcuts_group():
        """Manage desktop shortcuts for Thomas."""
        pass

    @shortcuts_group.command("install")
    @click.option(
        "--mode", type=click.Choice(["repl", "serve", "both"]), default="both", help="Which shortcut(s) to create"
    )
    def install_cmd(mode):
        """Create desktop shortcuts to launch Thomas."""
        created = install_shortcuts(mode)
        if created:
            click.echo(click.style("Shortcuts created:", fg="green"))
            for p in created:
                click.echo(f"  {p}")
        else:
            click.echo(click.style("Could not create shortcuts on this platform.", fg="red"))

    @shortcuts_group.command("remove")
    def remove_cmd():
        """Remove Thomas desktop shortcuts."""
        removed = remove_shortcuts()
        if removed:
            click.echo(click.style("Shortcuts removed:", fg="green"))
            for p in removed:
                click.echo(f"  {p}")
        else:
            click.echo("No shortcuts found to remove.")
