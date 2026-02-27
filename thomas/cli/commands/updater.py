"""Auto-update system for Thomas.

Checks PyPI for new versions and installs updates automatically.
Consumers get seamless updates. Dev installs (editable) are skipped.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

logger = logging.getLogger(__name__)

# Package name on PyPI
PYPI_PACKAGE = "thomas-ai"
# Check for updates at most once per day
UPDATE_CHECK_INTERVAL_S = 86400
# State file for last check timestamp
_STATE_DIR = Path.home() / ".thomas" / "updater"


def _get_current_version() -> str:
    """Get the currently installed version."""
    try:
        from thomas import __version__

        return str(__version__)
    except ImportError:
        return "0.0.0"


def _is_dev_install() -> bool:
    """Check if Thomas is installed in editable/dev mode."""
    try:
        import thomas

        pkg_path = Path(thomas.__file__).resolve().parent
        # Editable installs have .egg-link or the package is inside a
        # working tree (not in site-packages)
        site_packages = any("site-packages" in str(p) for p in [pkg_path])
        if not site_packages:
            # Likely an editable install or running from source
            return True

        # Also check for .egg-link files
        for sp in sys.path:
            egg_link = Path(sp) / f"{PYPI_PACKAGE}.egg-link"
            if egg_link.exists():
                return True
            egg_link2 = Path(sp) / "thomas.egg-link"
            if egg_link2.exists():
                return True
        return False
    except ImportError:
        return True  # Default to dev to avoid breaking dev setups


def _fetch_latest_version(timeout: float = 5.0) -> str | None:
    """Check PyPI for the latest version of thomas-ai."""
    try:
        import urllib.request

        url = f"https://pypi.org/pypi/{PYPI_PACKAGE}/json"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return str(data.get("info", {}).get("version", ""))
    except Exception as e:
        logger.debug("Failed to check PyPI for updates: %s", e)
        return None


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple."""
    parts = []
    for segment in str(v).strip().split("."):
        # Strip any pre-release suffixes for comparison
        num = ""
        for ch in segment:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)


def _is_newer(latest: str, current: str) -> bool:
    """Check if latest version is newer than current."""
    return _parse_version(latest) > _parse_version(current)


def _state_file() -> Path:
    """Get path to the updater state file."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    return _STATE_DIR / "state.json"


def _load_state() -> dict:
    """Load updater state."""
    path = _state_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(state: dict) -> None:
    """Save updater state."""
    path = _state_file()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _should_check() -> bool:
    """Check if enough time has passed since last update check."""
    state = _load_state()
    last_check = float(state.get("last_check_ts", 0))
    return (time.time() - last_check) > UPDATE_CHECK_INTERVAL_S


def _run_pip_upgrade() -> tuple[bool, str]:
    """Run pip upgrade for thomas-ai."""
    try:
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            PYPI_PACKAGE,
            "--quiet",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True, result.stdout.strip() or "Updated successfully"
        return False, result.stderr.strip() or f"pip exited with code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Update timed out after 120s"
    except Exception as e:
        return False, str(e)


def check_and_auto_update(*, silent: bool = True) -> str | None:
    """Check for updates and auto-install if available.

    Called on startup. Returns a message string if an update happened,
    or None if no action was taken.

    Args:
        silent: If True, suppress output (background check).
    """
    # Skip in dev mode — don't overwrite dev installs
    if _is_dev_install():
        logger.debug("Skipping auto-update: dev/editable install detected")
        return None

    # Skip if disabled via environment
    if os.environ.get("THOMAS_NO_AUTO_UPDATE", "").strip().lower() in ("1", "true", "yes"):
        return None

    # Rate limit checks
    if not _should_check():
        return None

    current = _get_current_version()
    latest = _fetch_latest_version()

    # Record that we checked
    state = _load_state()
    state["last_check_ts"] = time.time()
    state["last_check_version"] = latest or ""
    state["current_version"] = current

    if not latest:
        _save_state(state)
        return None

    if not _is_newer(latest, current):
        state["up_to_date"] = True
        _save_state(state)
        return None

    # New version available — auto-install
    logger.info("Updating Thomas from %s to %s...", current, latest)
    ok, msg = _run_pip_upgrade()

    state["last_update_ts"] = time.time()
    state["last_update_ok"] = ok
    state["last_update_msg"] = msg
    state["updated_from"] = current
    state["updated_to"] = latest if ok else ""
    state["up_to_date"] = ok
    _save_state(state)

    if ok:
        return f"Thomas updated: {current} → {latest}"
    else:
        logger.warning("Auto-update failed: %s", msg)
        return None


def register_update_commands(cli_group: click.Group) -> None:
    """Register the update command with the CLI."""

    @cli_group.command("update")
    @click.option("--check", "check_only", is_flag=True, help="Check for updates without installing")
    @click.option("--force", is_flag=True, help="Force update even in dev mode")
    def update_cmd(check_only: bool, force: bool) -> None:
        """Check for and install Thomas updates."""
        current = _get_current_version()
        click.echo(f"  Current version: {current}")

        if _is_dev_install() and not force:
            click.echo(
                click.style(
                    "  Dev/editable install detected — auto-update skipped.\n"
                    "  Use --force to override, or pull from git instead:\n"
                    "    git pull && pip install -e .",
                    fg="yellow",
                )
            )
            return

        click.echo("  Checking PyPI for updates...")
        latest = _fetch_latest_version(timeout=10.0)

        if not latest:
            click.echo(click.style("  Could not reach PyPI.", fg="red"))
            return

        click.echo(f"  Latest version:  {latest}")

        if not _is_newer(latest, current):
            click.echo(click.style("  Already up to date!", fg="green"))
            # Update state
            state = _load_state()
            state["last_check_ts"] = time.time()
            state["up_to_date"] = True
            _save_state(state)
            return

        if check_only:
            click.echo(
                click.style(
                    f"  Update available: {current} → {latest}\n" f"  Run 'thomas update' to install.",
                    fg="yellow",
                )
            )
            return

        click.echo(f"  Updating {current} → {latest}...")
        ok, msg = _run_pip_upgrade()

        if ok:
            click.echo(click.style(f"  Updated to {latest}!", fg="green"))
            click.echo("  Restart Thomas to use the new version.")
        else:
            click.echo(click.style(f"  Update failed: {msg}", fg="red"))

        # Save state
        state = _load_state()
        state["last_check_ts"] = time.time()
        state["last_update_ts"] = time.time()
        state["last_update_ok"] = ok
        state["updated_from"] = current
        state["updated_to"] = latest if ok else ""
        _save_state(state)

    @cli_group.command("version")
    @click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
    def version_cmd(as_json: bool) -> None:
        """Show Thomas version and update status."""
        current = _get_current_version()
        is_dev = _is_dev_install()
        state = _load_state()

        payload = {
            "version": current,
            "package": PYPI_PACKAGE,
            "dev_install": is_dev,
            "auto_update_enabled": not is_dev
            and os.environ.get("THOMAS_NO_AUTO_UPDATE", "").strip().lower() not in ("1", "true", "yes"),
            "last_check": state.get("last_check_ts"),
            "up_to_date": state.get("up_to_date"),
            "last_update": state.get("last_update_ts"),
        }

        if as_json:
            click.echo(json.dumps(payload, indent=2))
            return

        click.echo(f"  Thomas v{current}")
        if is_dev:
            click.echo(click.style("  (dev/editable install)", fg="yellow"))
        else:
            up = state.get("up_to_date")
            if up:
                click.echo(click.style("  Up to date", fg="green"))
            elif up is False:
                click.echo(click.style("  Update available", fg="yellow"))
