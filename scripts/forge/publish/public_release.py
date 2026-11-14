"""One call to see what would go public, and one to send a review copy to GitHub.

The app calls :func:`build` and :func:`publish` (and :func:`confirm` for the sign-in); the command line does the same:

    python -m scripts.forge.publish.public_release preview
    python -m scripts.forge.publish.public_release publish [--open-pr] [--dry-run]

``publish`` builds the preview, prints it, asks for a Windows sign-in for exactly that preview and only then sends
anything, to a branch named ``release/<version>-<date>``. There is no flag, setting or variable that skips the sign-in,
and nothing here writes to ``main``. Public history is permanent, so this is never run on a schedule.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.forge.publish.public_release_preview import Preview, ReleaseError, build, git  # noqa: E402
from scripts.forge.publish.public_release_publish import (  # noqa: E402
    Confirmation,
    PublishResult,
    confirm,
    publish,
)

__all__ = [
    "Confirmation",
    "Preview",
    "PublishResult",
    "ReleaseError",
    "build",
    "confirm",
    "describe",
    "main",
    "publish",
]


def describe(preview: Preview) -> str:
    """The preview in plain words."""
    lines = [
        f"Version {preview.version}: {preview.files} files would go public.",
        f"{len(preview.removed)} private files are left out:",
    ]
    reasons: dict[str, int] = {}
    for reason in preview.removed.values():
        reasons[reason] = reasons.get(reason, 0) + 1
    lines += [f"  {count} x {reason}" for reason, count in sorted(reasons.items())]
    if preview.branch:
        lines.append(f"A review copy would go to {preview.remote_url} as the branch {preview.branch}.")
    if preview.changed is not None:
        lines.append(f"{preview.changed} files differ from {preview.public_ref} on GitHub.")
    lines += [f"{'OK  ' if c.ok else 'FAIL'} {c.name}: {c.reason}" for c in preview.checks]
    lines.append("Safe to publish." if preview.safe_to_publish else "Not safe to publish yet.")
    return "\n".join(lines)


def _remote(repo: Path, named: str) -> str:
    return named or git(["remote", "get-url", "origin"], repo)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="See what would go public, or send a review copy to GitHub.")
    parser.add_argument("action", choices=("preview", "publish"))
    parser.add_argument("--repo", default=".", help="The development checkout to release from.")
    parser.add_argument("--ref", default="HEAD", help="The commit to release (default: HEAD).")
    parser.add_argument("--remote", default="", help="The public repository (default: this checkout's origin).")
    parser.add_argument("--public-ref", default="main", help="The branch the review is against (default: main).")
    parser.add_argument("--open-pr", action="store_true", help="Also open a pull request from the new branch.")
    parser.add_argument("--dry-run", action="store_true", help="Make the commit but send nothing.")
    parser.add_argument("--json", action="store_true", help="Print the preview as JSON.")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        remote = _remote(repo, args.remote)
        preview = build(repo, ref=args.ref, remote=remote, public_ref=args.public_ref)
    except ReleaseError as exc:
        print(f"Nothing was done: {exc}")
        return 2
    try:
        print(json.dumps(preview.to_dict(), indent=2) if args.json else describe(preview))
        if args.action == "preview":
            return 0 if preview.safe_to_publish else 1
        if not preview.safe_to_publish:
            return 1
        record = confirm(preview)
        result = publish(preview, record, open_pr=args.open_pr, dry_run=args.dry_run)
        print("\n".join(result.lines))
        return 0 if result.ok else 1
    finally:
        preview.close()


if __name__ == "__main__":
    raise SystemExit(main())
