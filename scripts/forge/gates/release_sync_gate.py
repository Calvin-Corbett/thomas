#!/usr/bin/env python3
"""Confirm a push is actually FINISHED, the way a release-engineering team means it.

Pushing commits is not shipping. On a professional team a change is released
when four records agree:

  1. the code is on the remote (nothing sitting unpushed),
  2. the version in ``pyproject.toml`` / ``thomas/__init__.py`` has its own
     dated section in ``CHANGELOG.md`` (not still pooled under Unreleased),
  3. an annotated tag ``vX.Y.Z`` exists for it ON THE REMOTE, pointing at code
     that is actually part of the shipped history, and
  4. a GitHub Release is published for that tag.

When those drift, the repository tells four different stories: the code says
0.19.25, the changelog's newest release says 0.19.22, and the Releases page
says 0.16.11 - which is exactly the state this gate was written for. Anyone
reading the project cannot tell what is actually shipped.

This gate REPORTS; it never edits. Run it before claiming a push is done.

A NOTE ON WHAT THIS GATE MAY SAY
--------------------------------
A gate that reports a record it did not read is worse than no gate, because it
converts an unknown into a false assurance. So every check here is tracked as
either CHECKED or SKIPPED, and the pass line names only the records actually
read. ``--no-remote-calls`` cannot produce a clean bill of health for the two
records that only exist on the remote; it reports them as unverified instead.

Usage:
    python scripts/forge/gates/release_sync_gate.py
    python scripts/forge/gates/release_sync_gate.py --remote dev-origin --branch dev
    python scripts/forge/gates/release_sync_gate.py --repo Calvin-Corbett/thomas
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

# gh exits non-zero for "no such release" and for "your token expired" alike.
# Treating the second as the first would report a missing release that may well
# exist, so the stderr is inspected rather than the exit code alone.
_AUTH_TROUBLE = ("authentication", "not logged", "HTTP 401", "HTTP 403", "gh auth login")
_NETWORK_TROUBLE = ("could not resolve", "dial tcp", "connection refused", "timeout", "TLS handshake")


def _run(binary: str, *args: str, timeout: int = 60) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed binary, literal args
            [binary, *args], cwd=str(REPO_ROOT), capture_output=True, text=True,
            timeout=timeout, check=False, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return 127, "", f"{binary} could not be run"
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _git(*args: str, timeout: int = 60) -> tuple[int, str]:
    code, out, _ = _run("git", *args, timeout=timeout)
    return code, out


def _gh(*args: str, timeout: int = 90) -> tuple[int, str, str]:
    return _run("gh", *args, timeout=timeout)


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


class _Report:
    """Accumulates findings while remembering which records were actually read."""

    def __init__(self) -> None:
        self.findings: list[dict[str, str]] = []
        self.checked: list[str] = []
        self.skipped: list[dict[str, str]] = []

    def fail(self, check: str, detail: str) -> None:
        self.findings.append({"check": check, "detail": detail})
        if check not in self.checked:
            self.checked.append(check)

    def passed(self, check: str) -> None:
        if check not in self.checked:
            self.checked.append(check)

    def unverified(self, check: str, why: str) -> None:
        """Record that a check could NOT be performed. Never a pass, never a fail."""
        self.skipped.append({"check": check, "reason": why})


def _check_pushed(report: _Report, remote: str, branch: str) -> None:
    code, _ = _git("fetch", remote, branch, "--quiet", timeout=180)
    if code != 0:
        report.unverified("code_is_pushed", f"could not fetch {remote}/{branch} (offline, or no such branch)")
        return
    _, ahead = _git("rev-list", "--count", f"{remote}/{branch}..HEAD")
    if ahead.isdigit() and int(ahead) > 0:
        report.fail("code_is_pushed", f"{ahead} commit(s) on HEAD are not on {remote}/{branch}")
    else:
        report.passed("code_is_pushed")


def _check_tag(report: _Report, version: str, remote: str, *, remote_calls: bool) -> None:
    code, _ = _git("rev-parse", "-q", "--verify", f"refs/tags/v{version}")
    if code != 0:
        report.fail("tag_exists", f"no git tag v{version} - tag the release commit")
        return
    report.passed("tag_exists")

    # A tag on a commit nobody shipped is a tag that lies about what is released.
    code, _ = _git("merge-base", "--is-ancestor", f"v{version}^{{commit}}", "HEAD")
    if code != 0:
        report.fail(
            "tag_points_at_shipped_code",
            f"tag v{version} is not an ancestor of HEAD - it labels code this branch does not contain",
        )
    else:
        report.passed("tag_points_at_shipped_code")

    # A LOCAL tag is invisible to everyone else. This gate exists to catch drift
    # between what this machine believes and what the world can see, so the tag
    # must be confirmed on the remote, not merely in .git/refs/tags.
    if not remote_calls:
        report.unverified("tag_is_pushed", "remote calls disabled")
        return
    code, out = _git("ls-remote", "--tags", remote, f"refs/tags/v{version}", timeout=120)
    if code != 0:
        report.unverified("tag_is_pushed", f"could not reach {remote} to list tags")
    elif not out.strip():
        report.fail("tag_is_pushed", f"tag v{version} exists locally but is NOT on {remote} - git push {remote} v{version}")
    else:
        report.passed("tag_is_pushed")


def _check_github_release(report: _Report, version: str, repo: str) -> None:
    args = ["release", "view", f"v{version}", "--json", "tagName"]
    if repo:
        args += ["--repo", repo]
    code, _, err = _gh(*args)
    where = f" on {repo}" if repo else ""
    if code == 127:
        report.unverified("github_release_published", "gh CLI unavailable")
        return
    lowered = err.lower()
    if any(sign.lower() in lowered for sign in _AUTH_TROUBLE):
        report.unverified("github_release_published", f"gh is not authenticated{where}: {err.splitlines()[0] if err else ''}")
        return
    if any(sign.lower() in lowered for sign in _NETWORK_TROUBLE):
        report.unverified("github_release_published", f"could not reach GitHub{where}")
        return
    if code != 0:
        report.fail("github_release_published", f"no published GitHub Release for v{version}{where}")
    else:
        report.passed("github_release_published")


def evaluate(remote: str, branch: str, *, remote_calls: bool = True, repo: str = "") -> dict:
    """Return the release-record findings. Never mutates anything."""
    report = _Report()
    version, version_problems = declared_version()
    for problem in version_problems:
        report.fail("version_sources_agree", problem)
    if version and not version_problems:
        report.passed("version_sources_agree")

    released = newest_released_section()

    if remote_calls:
        _check_pushed(report, remote, branch)
    else:
        report.unverified("code_is_pushed", "remote calls disabled")

    if version and released and version != released:
        report.fail(
            "changelog_has_this_version",
            f"code is {version} but the newest released CHANGELOG section is {released} - "
            f"cut a [{version}] section from Unreleased",
        )
    elif version and not released:
        report.fail("changelog_has_this_version", f"CHANGELOG.md has no released version section at all (code is {version})")
    elif version:
        report.passed("changelog_has_this_version")

    if version:
        _check_tag(report, version, remote, remote_calls=remote_calls)
        if remote_calls:
            _check_github_release(report, version, repo)
        else:
            report.unverified("github_release_published", "remote calls disabled")

    if unreleased_has_entries() and version and released and version != released:
        report.fail("unreleased_is_not_stale", "CHANGELOG [Unreleased] holds shipped work that no release section covers")

    return {
        "ok": not report.findings,
        "complete": not report.findings and not report.skipped,
        "version": version,
        "newest_released_section": released,
        "remote": f"{remote}/{branch}",
        "repo": repo,
        "findings": report.findings,
        "checked": report.checked,
        "unverified": report.skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="dev")
    parser.add_argument("--repo", default="", help="owner/name to check Releases on (defaults to gh's guess)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-remote-calls", action="store_true", help="skip fetch and gh lookups")
    args = parser.parse_args()

    result = evaluate(args.remote, args.branch, remote_calls=not args.no_remote_calls, repo=args.repo)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if result["ok"]:
        records = ", ".join(result["checked"]) or "nothing"
        if result["complete"]:
            print(f"Release sync: PASS - v{result['version']} is pushed, cut, tagged, and published.")
            print(f"  records read: {records}")
            return 0
        # Some record could not be read. Say exactly that, and do not imply the
        # unread ones are fine - an unknown reported as a pass is the failure
        # this gate exists to prevent.
        print(f"Release sync: INCOMPLETE - v{result['version']} passed every record that could be read.")
        print(f"  records read ...... {records}")
        print("  NOT verified ......")
        for skipped in result["unverified"]:
            print(f"    - [{skipped['check']}] {skipped['reason']}")
        print("  Re-run with network and an authenticated gh to finish the check.")
        return 2

    print("RELEASE SYNC GATE FAILED: the repository tells more than one story")
    print("=" * 70)
    print(f"  code version .......... {result['version'] or '(unknown)'}")
    print(f"  newest release notes .. {result['newest_released_section'] or '(none)'}")
    print(f"  compared against ...... {result['remote']}")
    print()
    print("WHAT IS OUT OF SYNC:")
    for finding in result["findings"]:
        print(f"  - [{finding['check']}] {finding['detail']}")
    if result["unverified"]:
        print()
        print("COULD NOT BE CHECKED (unknown, not necessarily fine):")
        for skipped in result["unverified"]:
            print(f"  - [{skipped['check']}] {skipped['reason']}")
    print()
    print("HOW A RELEASE IS FINISHED:")
    print("  1. Move CHANGELOG [Unreleased] entries into a dated [X.Y.Z] section.")
    print("  2. Make pyproject.toml and thomas/__init__.py agree with that version.")
    print("  3. git tag -a vX.Y.Z -m 'Thomas X.Y.Z' && git push <remote> vX.Y.Z")
    print("  4. gh release create vX.Y.Z --notes-file <the section you just cut>")
    print("=" * 70)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
