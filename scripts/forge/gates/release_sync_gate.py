#!/usr/bin/env python3
"""Confirm a push is actually FINISHED, the way a release-engineering team means it.

Pushing commits is not shipping. On a professional team a change is released
when four records agree:

  1. the code is on the remote (nothing sitting unpushed),
  2. the version in ``pyproject.toml`` / ``thomas/__init__.py`` has its own
     dated section in ``CHANGELOG.md`` (not still pooled under Unreleased),
  3. an annotated tag ``vX.Y.Z`` exists for it, and
  4. a GitHub Release is published for that tag.

When those drift, the repository tells four different stories: the code says
0.19.25, the changelog's newest release says 0.19.22, and the Releases page
says 0.16.11 — which is exactly the state this gate was written for. Anyone
reading the project cannot tell what is actually shipped.

This gate REPORTS; it never edits. Run it before claiming a push is done.

Usage:
    python scripts/forge/gates/release_sync_gate.py
    python scripts/forge/gates/release_sync_gate.py --remote dev-origin --branch dev
    python scripts/forge/gates/release_sync_gate.py --json
    python scripts/forge/gates/release_sync_gate.py --no-remote-calls   # offline
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
INIT_PY = REPO_ROOT / "thomas" / "__init__.py"

_VERSION_SECTION = re.compile(r"^##\s*\[(\d+\.\d+\.\d+)\]", re.MULTILINE)
_UNRELEASED = re.compile(r"^##\s*\[Unreleased\]\s*$(.*?)(?=^##\s*\[|\Z)", re.MULTILINE | re.DOTALL)


def _git(*args: str, timeout: int = 60) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603 - fixed binary, literal args
        ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True,
        timeout=timeout, check=False, encoding="utf-8", errors="replace",
    )
    return proc.returncode, (proc.stdout or "").strip()


def _gh(*args: str, timeout: int = 90) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed binary, literal args
            ["gh", *args], cwd=str(REPO_ROOT), capture_output=True, text=True,
            timeout=timeout, check=False, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return proc.returncode, (proc.stdout or "").strip()


def declared_version() -> tuple[str, list[str]]:
    """The version the CODE claims, plus any disagreement between its sources."""
    problems: list[str] = []
    pyproject_version = ""
    init_version = ""
    if PYPROJECT.exists():
        match = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.MULTILINE)
        pyproject_version = match.group(1) if match else ""
    if INIT_PY.exists():
        match = re.search(r'^__version__\s*=\s*"([^"]+)"', INIT_PY.read_text(encoding="utf-8"), re.MULTILINE)
        init_version = match.group(1) if match else ""
    if pyproject_version and init_version and pyproject_version != init_version:
        problems.append(
            f"pyproject.toml says {pyproject_version} but thomas/__init__.py says {init_version}"
        )
    return (pyproject_version or init_version), problems


def newest_released_section() -> str:
    if not CHANGELOG.exists():
        return ""
    match = _VERSION_SECTION.search(CHANGELOG.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def unreleased_has_entries() -> bool:
    if not CHANGELOG.exists():
        return False
    match = _UNRELEASED.search(CHANGELOG.read_text(encoding="utf-8"))
    if not match:
        return False
    body = match.group(1)
    return any(line.strip().startswith(("-", "*", "###")) for line in body.splitlines())


def evaluate(remote: str, branch: str, *, remote_calls: bool = True) -> dict:
    """Return the release-record findings. Never mutates anything."""
    findings: list[dict[str, str]] = []
    version, version_problems = declared_version()
    for problem in version_problems:
        findings.append({"check": "version_sources_agree", "detail": problem})

    released = newest_released_section()

    # 1. Is the branch actually pushed?
    if remote_calls:
        code, _ = _git("fetch", remote, branch, "--quiet", timeout=180)
        if code == 0:
            _, ahead = _git("rev-list", "--count", f"{remote}/{branch}..HEAD")
            if ahead.isdigit() and int(ahead) > 0:
                findings.append({
                    "check": "code_is_pushed",
                    "detail": f"{ahead} commit(s) on HEAD are not on {remote}/{branch}",
                })
        else:
            findings.append({
                "check": "code_is_pushed",
                "detail": f"could not fetch {remote}/{branch} to compare (offline or no such branch)",
            })

    # 2. Does the shipped version have its own changelog section?
    if version and released and version != released:
        findings.append({
            "check": "changelog_has_this_version",
            "detail": (
                f"code is {version} but the newest released CHANGELOG section is {released} - "
                f"cut a [{version}] section from Unreleased"
            ),
        })
    elif version and not released:
        findings.append({
            "check": "changelog_has_this_version",
            "detail": f"CHANGELOG.md has no released version section at all (code is {version})",
        })

    # 3. Does a tag exist for it?
    if version:
        code, _ = _git("rev-parse", "-q", "--verify", f"refs/tags/v{version}")
        if code != 0:
            findings.append({
                "check": "tag_exists",
                "detail": f"no git tag v{version} - tag the release commit",
            })

    # 4. Is a GitHub Release published for it?
    if version and remote_calls:
        code, out = _gh("release", "view", f"v{version}", "--json", "tagName")
        if code == 127:
            findings.append({
                "check": "github_release_published",
                "detail": "gh CLI unavailable, could not confirm a published Release",
            })
        elif code != 0:
            findings.append({
                "check": "github_release_published",
                "detail": f"no published GitHub Release for v{version}",
            })

    # 5. Unreleased entries with nothing cut = work shipped with no notes.
    if unreleased_has_entries() and version and released and version != released:
        findings.append({
            "check": "unreleased_is_not_stale",
            "detail": "CHANGELOG [Unreleased] holds shipped work that no release section covers",
        })

    return {
        "ok": not findings,
        "version": version,
        "newest_released_section": released,
        "remote": f"{remote}/{branch}",
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="dev")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-remote-calls", action="store_true", help="skip fetch and gh lookups")
    args = parser.parse_args()

    result = evaluate(args.remote, args.branch, remote_calls=not args.no_remote_calls)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if result["ok"]:
        print(f"Release sync: PASS - v{result['version']} is pushed, cut, tagged, and published.")
        return 0

    print("RELEASE SYNC GATE FAILED: the repository tells more than one story")
    print("=" * 70)
    print(f"  code version .......... {result['version'] or '(unknown)'}")
    print(f"  newest release notes .. {result['newest_released_section'] or '(none)'}")
    print(f"  compared against ...... {result['remote']}")
    print()
    print("WHAT IS OUT OF SYNC:")
    for finding in result["findings"]:
        print(f"  - [{finding['check']}] {finding['detail']}")
    print()
    print("HOW A RELEASE IS FINISHED:")
    print("  1. Move CHANGELOG [Unreleased] entries into a dated [X.Y.Z] section.")
    print("  2. Bump the version in pyproject.toml and thomas/__init__.py to match.")
    print("  3. git tag -a vX.Y.Z -m 'Thomas X.Y.Z' && git push <remote> vX.Y.Z")
    print("  4. gh release create vX.Y.Z --notes-file <the section you just cut>")
    print("=" * 70)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
