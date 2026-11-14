"""Who can write Thomas's code, against the set you approved.

A promotion lands on ``dev`` and in the running copy. That only means something
if nobody else can write those files around it, so before asking you anything
the promoter lists every principal allowed to write Thomas's code, git config
and hooks, and refuses if any is not in the pinned baseline.

The baseline is ``writers.allow`` in the pin folder (C:\\ProgramData\\ThomasPins),
written by ``scripts/cage/pin_writers.ps1`` -- elevated, so it is a set you
approved at a UAC prompt and one your own unelevated processes cannot change.
Measured 2026-09-22 it holds you, SYSTEM, Administrators, CodexSandboxUsers and
five unresolved SIDs that sit beside it (the Codex sandbox's writable roots,
spec fact 7): your own tools, which the spec's residual risks already trust.
Anything new -- a sixth SID, the cage's own account gaining write -- is refused.
No baseline, or one that cannot be read, refuses everything.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ALLOW_NAME = "writers.allow"
AUDITED = (
    "thomas",
    "scripts",
    "agent_safety.toml",
    "AGENTS.md",
    "CLAUDE.md",
    "GUARDRAILS.md",
    ".git/config",
    ".git/hooks",
)
_ALWAYS = frozenset({"S-1-5-18", "S-1-5-32-544"})  # SYSTEM, Administrators

# Allow entries that can write, create, delete or take over; SIDs, never names,
# so a renamed account or group cannot hide.
_LIST_WRITERS = r"""
$ErrorActionPreference = 'Stop'
$writeish = 'Write|Modify|FullControl|Delete|ChangePermissions|TakeOwnership|CreateFiles|AppendData'
foreach ($rel in $args) {
  if (-not (Test-Path -LiteralPath $rel)) { continue }
  (Get-Acl -LiteralPath $rel).Access |
    Where-Object { $_.AccessControlType -eq 'Allow' -and $_.FileSystemRights.ToString() -match $writeish } |
    ForEach-Object {
      try { $sid = $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }
      catch { $sid = $_.IdentityReference.Value }
      "$sid|$rel"
    }
}
"""


def current_writers(repo: Path) -> dict[str, list[str]]:
    """SID -> the audited paths it can write. Raises OSError if it cannot tell."""
    if os.name != "nt":
        return {}
    done = subprocess.run(
        # -Command pastes trailing words onto the script text, so the list is
        # passed to a script block instead. The paths are this module's constants.
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"& {{{_LIST_WRITERS}}} " + " ".join(f"'{rel}'" for rel in AUDITED),
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        # Runs inside the promoter, as you, with no console: without this every
        # audit put a PowerShell window on your screen.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if done.returncode != 0:
        raise OSError(f"could not read the permissions on Thomas's code: {done.stderr.strip()[:300]}")
    found: dict[str, list[str]] = {}
    for line in done.stdout.splitlines():
        sid, _, rel = line.strip().partition("|")
        if sid and rel:
            found.setdefault(sid, []).append(rel)
    return found


def unexpected_writers(repo: Path, *, pin_root: Path | None = None) -> list[str]:
    """Writers not in the pinned baseline, as "SID on path, path". Empty is clean."""
    if os.name != "nt":
        return []
    if pin_root is None:
        from thomas.tools.cage_shell import DEFAULT_PIN_ROOT

        pin_root = DEFAULT_PIN_ROOT
    try:
        allowed = {s.strip() for s in (Path(pin_root) / ALLOW_NAME).read_text(encoding="utf-8-sig").split()}
    except OSError:
        return ["the writer baseline is not pinned (run scripts/cage/pin_writers.ps1 elevated)"]
    try:
        writers = current_writers(repo)
    except OSError as exc:
        return [str(exc)]
    return sorted(f"{sid} on {', '.join(paths)}" for sid, paths in writers.items() if sid not in allowed | _ALWAYS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List who can write Thomas's code.")
    parser.add_argument("--current", metavar="REPO", help="print every writer SID, one per line (for the pin)")
    args = parser.parse_args(argv)
    if args.current:
        for sid in sorted(current_writers(Path(args.current))):
            print(sid)
        return 0
    repo = Path(__file__).resolve().parents[2]
    problems = unexpected_writers(repo)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
