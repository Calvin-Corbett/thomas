"""Update checks and explicit release application for Thomas.

Startup performs a cached PyPI check only. Installing a new release is always
an explicit user action and may be blocked by the active security profile.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

logger = logging.getLogger(__name__)

PYPI_PACKAGE = "thomas-ai"
UPDATE_CHECK_INTERVAL_S = 86400
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
        if "site-packages" not in str(pkg_path):
            return True

        for sp in sys.path:
            egg_link = Path(sp) / f"{PYPI_PACKAGE}.egg-link"
            if egg_link.exists():
                return True
            egg_link2 = Path(sp) / "thomas.egg-link"
            if egg_link2.exists():
                return True
        return False
    except ImportError:
        return True


def _fetch_latest_release(timeout: float = 5.0) -> dict[str, str] | None:
    """Fetch the latest release metadata from PyPI."""
    try:
        import urllib.request

        url = f"https://pypi.org/pypi/{PYPI_PACKAGE}/json"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.debug("Failed to check PyPI for updates: %s", exc)
        return None

    latest = str(data.get("info", {}).get("version", "") or "").strip()
    if not latest:
        return None

    published_at = ""
    releases = data.get("releases", {})
    if isinstance(releases, dict):
        files = releases.get(latest)
        if isinstance(files, list):
            timestamps = []
            for item in files:
                if not isinstance(item, dict):
                    continue
                raw = str(item.get("upload_time_iso_8601") or item.get("upload_time") or "").strip()
                if raw:
                    timestamps.append(raw)
            if timestamps:
                published_at = sorted(timestamps)[0]

    return {"version": latest, "published_at": published_at}


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple."""
    parts = []
    for segment in str(v).strip().split("."):
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


def _load_state() -> dict[str, Any]:
    """Load updater state."""
    path = _state_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(state: dict[str, Any]) -> None:
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return True, result.stdout.strip() or "Updated successfully"
        return False, result.stderr.strip() or f"pip exited with code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Update timed out after 120s"
    except Exception as exc:
        return False, str(exc)


def _load_runtime_config():
    try:
        from thomas.core.config import load_config

        return load_config()
    except Exception as exc:
        logger.debug("Failed to load config for updater policy: %s", exc)
        return None


def _resolve_security_context(config=None) -> tuple[str, dict[str, Any]]:
    if config is None:
        config = _load_runtime_config()
    if config is None:
        return "locked", {
            "tool_install_allowed": False,
            "tool_install_requires_confirmation": False,
            "update_apply_allowed": False,
            "update_apply_requires_confirmation": False,
            "startup_update_checks_allowed": True,
            "background_mutation_allowed": False,
            "assistant_guided_installs": False,
            "blocked_actions": {
                "tool_install": "Config could not be loaded, so tool installation is blocked.",
                "update_apply": "Config could not be loaded, so update apply is blocked.",
            },
        }
    return config.security_profile, config.security_capabilities()


def _startup_checks_disabled() -> bool:
    return os.environ.get("THOMAS_NO_AUTO_UPDATE", "").strip().lower() in ("1", "true", "yes")


def _format_release_suffix(published_at: str) -> str:
    value = str(published_at or "").strip()
    return f" (published {value})" if value else ""


def check_and_auto_update(*, silent: bool = True) -> str | None:
    """Check for updates on startup without applying them."""
    if _is_dev_install():
        logger.debug("Skipping startup update check: dev/editable install detected")
        return None

    if _startup_checks_disabled():
        return None

    if not _should_check():
        return None

    current = _get_current_version()
    release = _fetch_latest_release()

    state = _load_state()
    state["last_check_ts"] = time.time()
    state["current_version"] = current

    if not release:
        _save_state(state)
        return None

    latest = str(release.get("version") or "")
    published_at = str(release.get("published_at") or "")
    state["last_check_version"] = latest
    state["latest_release_published_at"] = published_at

    if not _is_newer(latest, current):
        state["up_to_date"] = True
        state["update_available"] = False
        _save_state(state)
        return None

    state["up_to_date"] = False
    state["update_available"] = True
    _save_state(state)

    message = f"Thomas update available: {current} -> {latest}{_format_release_suffix(published_at)}"
    return message if silent else message


def _run_update_flow(*, check_only: bool, force: bool, config=None) -> None:
    """Execute the user-facing update flow for both root and subcommands."""
    current = _get_current_version()
    security_profile, capabilities = _resolve_security_context(config)
    click.echo(f"  Current version: {current}")
    click.echo(f"  Security profile: {security_profile}")

    if _is_dev_install() and not force:
        click.echo(
            click.style(
                "  Dev/editable install detected - update apply skipped.\n"
                "  Use --force to override, or pull from git instead:\n"
                "    git pull && pip install -e .",
                fg="yellow",
            )
        )
        return

    click.echo("  Checking PyPI for updates...")
    release = _fetch_latest_release(timeout=10.0)

    state = _load_state()
    state["last_check_ts"] = time.time()
    state["current_version"] = current

    if not release:
        _save_state(state)
        click.echo(click.style("  Could not reach PyPI.", fg="red"))
        return

    latest = str(release.get("version") or "")
    published_at = str(release.get("published_at") or "")
    state["last_check_version"] = latest
    state["latest_release_published_at"] = published_at

    click.echo(f"  Latest version:  {latest}")
    if published_at:
        click.echo(f"  Release time:    {published_at}")

    if not _is_newer(latest, current):
        state["up_to_date"] = True
        state["update_available"] = False
        _save_state(state)
        click.echo(click.style("  Already up to date!", fg="green"))
        return

    state["up_to_date"] = False
    state["update_available"] = True

    if check_only:
        _save_state(state)
        click.echo(
            click.style(
                f"  Update available: {current} -> {latest}\n  Run 'thomas update apply' to install.",
                fg="yellow",
            )
        )
        return

    if not bool(capabilities.get("update_apply_allowed")):
        state["last_update_ts"] = time.time()
        state["last_update_ok"] = False
        state["last_update_msg"] = str(capabilities.get("blocked_actions", {}).get("update_apply") or "")
        _save_state(state)
        click.echo(
            click.style(
                "  Update apply blocked by security profile: "
                + str(capabilities.get("blocked_actions", {}).get("update_apply") or "not allowed"),
                fg="yellow",
            )
        )
        return

    click.echo(f"  Applying update {current} -> {latest}...")
    ok, msg = _run_pip_upgrade()

    state["last_update_ts"] = time.time()
    state["last_update_ok"] = ok
    state["last_update_msg"] = msg
    state["updated_from"] = current
    state["updated_to"] = latest if ok else ""
    state["up_to_date"] = ok
    state["update_available"] = not ok
    _save_state(state)

    if ok:
        click.echo(click.style(f"  Updated to {latest}!", fg="green"))
        click.echo("  Restart Thomas to use the new version.")
    else:
        click.echo(click.style(f"  Update failed: {msg}", fg="red"))


def register_update_commands(cli_group: click.Group) -> None:
    """Register the update command with the CLI."""

    @cli_group.group("update", invoke_without_command=True)
    @click.option("--check", "check_only", is_flag=True, help="Check for updates without installing")
    @click.option("--force", is_flag=True, help="Force update even in dev mode")
    @click.pass_context
    def update_cmd(ctx: click.Context, check_only: bool, force: bool) -> None:
        """Check for and install Thomas updates."""
        if ctx.invoked_subcommand is not None:
            return
        _run_update_flow(check_only=bool(check_only), force=bool(force), config=(ctx.obj or {}).get("config"))

    @update_cmd.command("check")
    @click.option("--force", is_flag=True, help="Force update checks even in dev mode")
    @click.pass_context
    def update_check_cmd(ctx: click.Context, force: bool) -> None:
        """Check for updates without installing them."""
        _run_update_flow(check_only=True, force=bool(force), config=(ctx.obj or {}).get("config"))

    @update_cmd.command("apply")
    @click.option("--force", is_flag=True, help="Force update even in dev mode")
    @click.pass_context
    def update_apply_cmd(ctx: click.Context, force: bool) -> None:
        """Download and install the latest Thomas release."""
        _run_update_flow(check_only=False, force=bool(force), config=(ctx.obj or {}).get("config"))

    @update_cmd.command("status")
    @click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
    @click.pass_context
    def update_status_cmd(ctx: click.Context, as_json: bool) -> None:
        """Show cached update-check status without contacting PyPI."""
        current = _get_current_version()
        state = _load_state()
        security_profile, capabilities = _resolve_security_context((ctx.obj or {}).get("config"))
        payload = {
            "version": current,
            "dev_install": _is_dev_install(),
            "security_profile": security_profile,
            "security_capabilities": capabilities,
            "last_check_ts": state.get("last_check_ts"),
            "last_check_version": state.get("last_check_version"),
            "latest_release_published_at": state.get("latest_release_published_at"),
            "last_update_ts": state.get("last_update_ts"),
            "last_update_ok": state.get("last_update_ok"),
            "last_update_msg": state.get("last_update_msg"),
            "updated_from": state.get("updated_from"),
            "updated_to": state.get("updated_to"),
            "up_to_date": state.get("up_to_date"),
            "update_available": state.get("update_available"),
            "startup_update_check_enabled": not _is_dev_install() and not _startup_checks_disabled(),
            "auto_update_enabled": False,
        }
        if as_json:
            click.echo(json.dumps(payload, indent=2))
            return
        click.echo(f"  Thomas v{current}")
        click.echo(f"  Security profile: {security_profile}")
        click.echo(f"  Up to date: {payload['up_to_date']}")
        click.echo(f"  Update available: {payload['update_available']}")
        click.echo(f"  Last check: {payload['last_check_ts']}")
        click.echo(f"  Last update: {payload['last_update_ts']}")

    @cli_group.command("version")
    @click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
    @click.pass_context
    def version_cmd(ctx: click.Context, as_json: bool) -> None:
        """Show Thomas version and update status."""
        current = _get_current_version()
        is_dev = _is_dev_install()
        state = _load_state()
        security_profile, capabilities = _resolve_security_context((ctx.obj or {}).get("config"))

        payload = {
            "version": current,
            "package": PYPI_PACKAGE,
            "dev_install": is_dev,
            "security_profile": security_profile,
            "security_capabilities": capabilities,
            "startup_update_check_enabled": not is_dev and not _startup_checks_disabled(),
            "auto_update_enabled": False,
            "last_check": state.get("last_check_ts"),
            "latest_known_version": state.get("last_check_version"),
            "latest_release_published_at": state.get("latest_release_published_at"),
            "up_to_date": state.get("up_to_date"),
            "last_update": state.get("last_update_ts"),
        }

        if as_json:
            click.echo(json.dumps(payload, indent=2))
            return

        click.echo(f"  Thomas v{current}")
        click.echo(f"  Security profile: {security_profile}")
        if is_dev:
            click.echo(click.style("  (dev/editable install)", fg="yellow"))
        else:
            up = state.get("up_to_date")
            if up:
                click.echo(click.style("  Up to date", fg="green"))
            elif up is False:
                click.echo(click.style("  Update available", fg="yellow"))
