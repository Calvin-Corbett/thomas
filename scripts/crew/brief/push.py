"""The sanctioned push path: push, then prove the push is actually finished.

Thomas has a gated way to COMMIT (``scripts/crew/brief/commit.py``) and, until
now, no gated way to PUSH — so code reached GitHub while the release record
stayed behind, and nothing objected. That is how the repository ended up
telling three stories at once: code at 0.19.25, newest release notes at
0.19.22, latest published Release at 0.16.11.

A push on a professional team is not "the bytes are on the remote". It is
finished when the code is pushed AND the release record matches it — the
version has its own dated changelog section, an annotated tag exists, and a
GitHub Release is published. This wraps the push and then runs
``release_sync_gate`` to say plainly whether that is true.

It never edits the release record for you: cutting a release is a decision,
and the version files are protected. It tells you exactly what is missing.

Usage:
    python scripts/crew/brief/push.py --remote dev-origin --branch dev
    python scripts/crew/brief/push.py --remote origin --ref dev:landing/x
    python scripts/crew/brief/push.py --remote origin --branch main --dry-run
    python scripts/crew/brief/push.py ... --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNC_GATE = REPO_ROOT / "scripts" / "forge" / "gates" / "release_sync_gate.py"


def _safe_print(text: str = "") -> None:
    """A console that cannot encode a character must not kill the report."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    safe = str(text).encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe)


def _run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    proc = subprocess.run(  # noqa: S603 - fixed binaries, caller-supplied refs only
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
        timeout=timeout, check=False, encoding="utf-8", errors="replace",
    )
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", required=True, help="git remote name, e.g. origin or dev-origin")
    parser.add_argument("--branch", default="", help="branch to push and to verify against")
    parser.add_argument("--ref", default="", help="explicit refspec, e.g. dev:landing/thing")
    parser.add_argument("--force-with-lease", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="verify only; do not push")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.branch and not args.ref:
        print("give --branch or --ref")
        return 2
    refspec = args.ref or args.branch
    # The branch the release record is judged against: for a refspec like
    # dev:landing/x the remote-side name is what actually exists there.
    verify_branch = args.branch or refspec.split(":", 1)[-1]

    report: dict[str, object] = {"remote": args.remote, "refspec": refspec, "pushed": False}

    if args.dry_run:
        print(f"[dry-run] would push {refspec} -> {args.remote}")
    else:
        cmd = ["git", "push", args.remote, refspec]
        if args.force_with_lease:
            cmd.insert(2, "--force-with-lease")
        code, out = _run(cmd)
        report["push_output"] = out[-1500:]
        report["pushed"] = code == 0
        if code != 0:
            report["ok"] = False
            report["error"] = "push failed"
            print(out[-2000:] if not args.json else json.dumps(report, indent=2))
            return 1
        print(f"pushed {refspec} -> {args.remote}")

    if not SYNC_GATE.exists():
        print("release_sync_gate.py is missing; cannot confirm the push is finished")
        return 1

    code, out = _run(
        [sys.executable, str(SYNC_GATE), "--remote", args.remote, "--branch", verify_branch],
        timeout=600,
    )
    report["release_sync_ok"] = code == 0
    report["release_sync_output"] = out

    if args.json:
        report["ok"] = bool(report.get("pushed") or args.dry_run) and code == 0
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    _safe_print("")
    _safe_print(out)
    if code != 0:
        print()
        print("The code is on the remote, but this push is NOT a finished release.")
        print("Cut the release record above, or say plainly that this is an")
        print("in-progress branch push and not a release.")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
