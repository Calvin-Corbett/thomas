"""Create a professional desktop shortcut for Thomas.

Cross-platform: Windows (.lnk), macOS (.command + Dock-friendly),
Linux (.desktop).  Generates the icon if it doesn't exist yet.

Usage:
    python scripts/create_shortcut.py              # auto-detect platform
    python scripts/create_shortcut.py --desktop     # force desktop location
    python scripts/create_shortcut.py --start-menu  # Windows Start Menu
    python scripts/create_shortcut.py --dry-run     # show what would happen
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

# ── Resolve paths ────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "assets"
ICO_PATH = ASSETS_DIR / "thomas.ico"
PNG_PATH = ASSETS_DIR / "thomas.png"
LAUNCH_CMD = REPO_ROOT / "run-ui.cmd"
LAUNCH_PS1 = REPO_ROOT / "scripts" / "run-ui.ps1"


def _ensure_icon() -> None:
    """Generate icons if they don't exist yet."""
    if ICO_PATH.exists() and PNG_PATH.exists():
        return
    try:
        from generate_icon import generate_ico, generate_png
    except ImportError:
        # Add scripts/ to path and retry
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from generate_icon import generate_ico, generate_png

    if not ICO_PATH.exists():
        generate_ico(ICO_PATH)
        print(f"  Generated {ICO_PATH}")
    if not PNG_PATH.exists():
        generate_png(PNG_PATH, 256)
        print(f"  Generated {PNG_PATH}")


def _get_desktop() -> Path:
    """Return the user's Desktop folder, cross-platform."""
    system = platform.system()
    if system == "Windows":
        # Use the Shell API for localized desktops
        try:
            import ctypes.wintypes

            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            # CSIDL_DESKTOPDIRECTORY = 0x0010
            ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)
            return Path(buf.value)
        except Exception:
            pass
        desktop = Path.home() / "Desktop"
        if desktop.exists():
            return desktop
        # OneDrive desktop
        onedrive = Path.home() / "OneDrive" / "Desktop"
        if onedrive.exists():
            return onedrive
        return desktop
    elif system == "Darwin":
        return Path.home() / "Desktop"
    else:
        # XDG
        try:
            result = subprocess.run(
                ["xdg-user-dir", "DESKTOP"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip())
        except Exception:
            pass
        return Path.home() / "Desktop"


# ── Windows ──────────────────────────────────────────────────────


def _create_windows_shortcut(
    target_dir: Path,
    name: str = "Thomas",
) -> Path:
    """Create a .lnk shortcut on Windows using PowerShell COM."""
    _ensure_icon()
    lnk = target_dir / f"{name}.lnk"

    # PowerShell script to create shortcut via WScript.Shell COM
    # We point to run-ui.cmd which chains to the PS1 launcher.
    ps_script = textwrap.dedent(f"""\
        $ws = New-Object -ComObject WScript.Shell
        $sc = $ws.CreateShortcut('{lnk}')
        $sc.TargetPath = '{LAUNCH_CMD}'
        $sc.WorkingDirectory = '{REPO_ROOT}'
        $sc.IconLocation = '{ICO_PATH},0'
        $sc.Description = 'Launch the Thomas AI Workspace'
        $sc.WindowStyle = 7
        $sc.Save()
    """)

    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create shortcut:\n{result.stderr}")

    return lnk


def _create_windows_start_menu(name: str = "Thomas") -> Path:
    """Create a Start Menu shortcut on Windows."""
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        appdata = str(Path.home() / "AppData" / "Roaming")
    start_menu = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    start_menu.mkdir(parents=True, exist_ok=True)
    return _create_windows_shortcut(start_menu, name)


# ── macOS ────────────────────────────────────────────────────────


def _create_macos_shortcut(
    target_dir: Path,
    name: str = "Thomas",
) -> Path:
    """Create a .command launcher with a custom icon on macOS."""
    _ensure_icon()

    # Create a .command file (double-clickable terminal script)
    cmd_file = target_dir / f"{name}.command"
    cmd_file.write_text(
        textwrap.dedent(f"""\
        #!/bin/bash
        # Thomas AI Workspace Launcher
        cd "{REPO_ROOT}"
        if command -v thomas &>/dev/null; then
            thomas serve
        elif [ -f ".venv/bin/thomas" ]; then
            .venv/bin/thomas serve
        elif [ -f "run-ui.cmd" ]; then
            python -m thomas.server
        else
            echo "Thomas not found. Run: pip install -e ."
            read -p "Press Enter to close..."
        fi
    """),
        encoding="utf-8",
    )
    cmd_file.chmod(cmd_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Set custom icon using the PNG via macOS resource forks
    _set_macos_icon(cmd_file)

    return cmd_file


def _set_macos_icon(target: Path) -> None:
    """Attempt to set a custom icon on a macOS file using sips + DeRez/Rez."""
    if not PNG_PATH.exists():
        return
    try:
        # Convert PNG to ICNS
        icns_path = ASSETS_DIR / "thomas.icns"
        if not icns_path.exists():
            iconset = ASSETS_DIR / "thomas.iconset"
            iconset.mkdir(exist_ok=True)
            for size in [16, 32, 64, 128, 256, 512]:
                subprocess.run(
                    [
                        "sips",
                        "-z",
                        str(size),
                        str(size),
                        str(PNG_PATH),
                        "--out",
                        str(iconset / f"icon_{size}x{size}.png"),
                    ],
                    capture_output=True,
                    timeout=15,
                )
                if size <= 256:
                    double = size * 2
                    subprocess.run(
                        [
                            "sips",
                            "-z",
                            str(double),
                            str(double),
                            str(PNG_PATH),
                            "--out",
                            str(iconset / f"icon_{size}x{size}@2x.png"),
                        ],
                        capture_output=True,
                        timeout=15,
                    )
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
                capture_output=True,
                timeout=30,
            )
            shutil.rmtree(iconset, ignore_errors=True)

        # Apply icon to file using fileicon CLI if available
        if icns_path.exists():
            subprocess.run(
                ["fileicon", "set", str(target), str(icns_path)],
                capture_output=True,
                timeout=15,
            )
    except Exception:
        pass  # Icon setting is best-effort on macOS


# ── Linux ────────────────────────────────────────────────────────


def _create_linux_shortcut(
    target_dir: Path,
    name: str = "Thomas",
) -> Path:
    """Create a .desktop file for Linux."""
    _ensure_icon()

    # Find the thomas executable
    thomas_bin = shutil.which("thomas")
    if thomas_bin:
        exec_line = f"{thomas_bin} serve"
    else:
        venv_bin = REPO_ROOT / ".venv" / "bin" / "thomas"
        if venv_bin.exists():
            exec_line = f"{venv_bin} serve"
        else:
            exec_line = "python -m thomas.server"

    desktop_file = target_dir / f"{name.lower()}.desktop"
    desktop_file.write_text(
        textwrap.dedent(f"""\
        [Desktop Entry]
        Version=1.1
        Type=Application
        Name={name}
        Comment=Launch the Thomas AI Workspace
        Exec={exec_line}
        Icon={PNG_PATH}
        Path={REPO_ROOT}
        Terminal=false
        Categories=Development;Utility;
        StartupNotify=true
        StartupWMClass=thomas
    """),
        encoding="utf-8",
    )

    desktop_file.chmod(desktop_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Trust the desktop file if gio is available
    import contextlib

    with contextlib.suppress(Exception):
        subprocess.run(
            ["gio", "set", str(desktop_file), "metadata::trusted", "true"],
            capture_output=True,
            timeout=10,
        )

    # Also install to ~/.local/share/applications for app launcher
    local_apps = Path.home() / ".local" / "share" / "applications"
    local_apps.mkdir(parents=True, exist_ok=True)
    app_desktop = local_apps / f"{name.lower()}.desktop"
    if not app_desktop.exists():
        shutil.copy2(desktop_file, app_desktop)

    return desktop_file


# ── Public API ───────────────────────────────────────────────────


def create_desktop_shortcut(name: str = "Thomas") -> Path:
    """Create a desktop shortcut for the current platform.  Returns the path."""
    desktop = _get_desktop()
    desktop.mkdir(parents=True, exist_ok=True)
    system = platform.system()

    if system == "Windows":
        return _create_windows_shortcut(desktop, name)
    elif system == "Darwin":
        return _create_macos_shortcut(desktop, name)
    else:
        return _create_linux_shortcut(desktop, name)


def create_start_menu_shortcut(name: str = "Thomas") -> Path | None:
    """Create a Start Menu / app launcher entry.  Windows + Linux only."""
    system = platform.system()
    if system == "Windows":
        return _create_windows_start_menu(name)
    elif system == "Linux":
        local_apps = Path.home() / ".local" / "share" / "applications"
        local_apps.mkdir(parents=True, exist_ok=True)
        return _create_linux_shortcut(local_apps, name)
    return None


# ── CLI ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Thomas desktop shortcut")
    parser.add_argument("--desktop", action="store_true", default=True, help="Create desktop shortcut (default)")
    parser.add_argument("--start-menu", action="store_true", help="Also create Start Menu / app launcher entry")
    parser.add_argument("--name", default="Thomas", help="Shortcut display name (default: Thomas)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without doing it")
    args = parser.parse_args()

    system = platform.system()
    print(f"Platform: {system}")
    print(f"Repo root: {REPO_ROOT}")

    if args.dry_run:
        desktop = _get_desktop()
        print("\nWould create:")
        if system == "Windows":
            print(f"  Desktop shortcut: {desktop / f'{args.name}.lnk'}")
            if args.start_menu:
                appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
                sm = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                print(f"  Start Menu: {sm / f'{args.name}.lnk'}")
        elif system == "Darwin":
            print(f"  Desktop launcher: {desktop / f'{args.name}.command'}")
        else:
            print(f"  Desktop entry: {desktop / f'{args.name.lower()}.desktop'}")
            print(f"  App launcher: ~/.local/share/applications/{args.name.lower()}.desktop")
        print("\nIcon files:")
        print(f"  ICO: {ICO_PATH} ({'exists' if ICO_PATH.exists() else 'will generate'})")
        print(f"  PNG: {PNG_PATH} ({'exists' if PNG_PATH.exists() else 'will generate'})")
        return

    # Generate icons first
    print("\nEnsuring icons exist...")
    _ensure_icon()

    # Desktop shortcut
    print("\nCreating desktop shortcut...")
    path = create_desktop_shortcut(args.name)
    print(f"  Created: {path}")

    # Start Menu
    if args.start_menu:
        print("\nCreating Start Menu entry...")
        sm_path = create_start_menu_shortcut(args.name)
        if sm_path:
            print(f"  Created: {sm_path}")
        else:
            print("  (Not applicable on this platform)")

    print("\nDone! Thomas shortcut is ready.")


if __name__ == "__main__":
    main()
