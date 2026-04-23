"""Version bump and release helper for Thomas.

Bumps version in both pyproject.toml and thomas/__init__.py,
commits, tags, and optionally pushes to trigger PyPI publish.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

logger = logging.getLogger(__name__)


def _find_project_root() -> Path | None:
    """Walk up from thomas package to find pyproject.toml."""
    try:
        import thomas

        pkg = Path(thomas.__file__).resolve().parent
        for candidate in [pkg.parent, pkg.parent.parent, Path.cwd()]:
            if (candidate / "pyproject.toml").exists():
                return candidate
    except ImportError:
        pass
    if (Path.cwd() / "pyproject.toml").exists():
        return Path.cwd()
    return None


def _parse_version(v: str) -> tuple[int, int, int]:
    """Parse major.minor.patch from version string."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", str(v).strip())
    if not m:
        raise ValueError(f"Cannot parse version: {v}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _bump(current: str, part: str) -> str:
    """Bump a version string by part (major, minor, patch)."""
    major, minor, patch = _parse_version(current)
    if part == "major":
        return f"{major + 1}.0.0"
    elif part == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


def _read_current_version(root: Path) -> str:
    """Read current version from pyproject.toml."""
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise ValueError("Cannot find version in pyproject.toml")
    return m.group(1)


def _write_version(root: Path, new_version: str) -> list:
    """Update version in both pyproject.toml and __init__.py."""
    updated = []

    # pyproject.toml
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    new_text = re.sub(
        r'^(version\s*=\s*")[^"]+"',
        f'\\g<1>{new_version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if new_text != text:
        pyproject.write_text(new_text, encoding="utf-8")
        updated.append(str(pyproject))

    # thomas/__init__.py
    init = root / "thomas" / "__init__.py"
    if init.exists():
        text = init.read_text(encoding="utf-8")
        new_text = re.sub(
            r'^(__version__\s*=\s*")[^"]+"',
            f'\\g<1>{new_version}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if new_text != text:
            init.write_text(new_text, encoding="utf-8")
            updated.append(str(init))

    return updated


def register_release_commands(cli_group: click.Group) -> None:
    """Register the release command with the CLI."""

    @cli_group.command("release")
    @click.argument("part", type=click.Choice(["major", "minor", "patch"]), default="patch")
    @click.option("--dry-run", is_flag=True, help="Show what would happen without doing it")
    @click.option("--push/--no-push", default=True, help="Push commit and tag to remote")
    def release_cmd(part: str, dry_run: bool, push: bool) -> None:
        """Bump version, commit, tag, and push to trigger PyPI publish.

        \b
        Examples:
          thomas release patch    # 0.11.78 -> 0.11.79
          thomas release minor    # 0.11.78 -> 0.12.0
          thomas release major    # 0.11.78 -> 1.0.0
        """
        root = _find_project_root()
        if not root:
            click.echo(
                click.style(
                    "  Cannot find project root (pyproject.toml).\n" "  Run this from the Thomas project directory.",
                    fg="red",
                )
            )
            sys.exit(1)

        current = _read_current_version(root)
        new_ver = _bump(current, part)

        click.echo(f"  Version bump: {current} -> {new_ver}")

        if dry_run:
            click.echo(click.style("  (dry run -- no changes made)", fg="yellow"))
            click.echo("  Would update: pyproject.toml, thomas/__init__.py")
            click.echo(f"  Would commit: 'Release v{new_ver}'")
            click.echo(f"  Would tag: v{new_ver}")
            if push:
                click.echo("  Would push: origin (triggers PyPI publish)")
            return

        # 1. Update version files
        updated = _write_version(root, new_ver)
        for f in updated:
            click.echo(f"  Updated: {f}")

        # 2. Git commit
        try:
            subprocess.run(
                ["git", "add"] + updated,
                cwd=str(root),
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", f"Release v{new_ver}", "--"] + updated,
                cwd=str(root),
                check=True,
                capture_output=True,
            )
            click.echo(f"  Committed: Release v{new_ver}")
        except subprocess.CalledProcessError as e:
            click.echo(click.style(f"  Git commit failed: {e.stderr.decode()[:200]}", fg="red"))
            sys.exit(1)

        # 3. Git tag
        try:
            subprocess.run(
                ["git", "tag", f"v{new_ver}"],
                cwd=str(root),
                check=True,
                capture_output=True,
            )
            click.echo(f"  Tagged: v{new_ver}")
        except subprocess.CalledProcessError as e:
            click.echo(click.style(f"  Git tag failed: {e.stderr.decode()[:200]}", fg="red"))
            sys.exit(1)

        # 4. Push (triggers GitHub Actions -> PyPI publish)
        if push:
            try:
                subprocess.run(
                    ["git", "push"],
                    cwd=str(root),
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "push", "--tags"],
                    cwd=str(root),
                    check=True,
                    capture_output=True,
                )
                click.echo(click.style("  Pushed! PyPI publish will start automatically.", fg="green"))
            except subprocess.CalledProcessError as e:
                click.echo(
                    click.style(
                        f"  Push failed: {e.stderr.decode()[:200]}\n"
                        f"  You can push manually: git push && git push --tags",
                        fg="yellow",
                    )
                )
        else:
            click.echo("  Skipped push. Run manually:")
            click.echo(click.style("    git push && git push --tags", fg="yellow"))

        click.echo("")
        click.echo(click.style(f"  Release v{new_ver} ready!", fg="green"))
