"""Claim the staged paths nobody else holds, so an uncontested file never refuses.

The claim gates refuse a commit whose files are not in your board claim -- including
files no agent on the board has any interest in. That refusal carries no safety:
nobody is being protected from anything, because nobody else wants the file. It is
pure ceremony, every agent pays it on every commit, and it is the most common reason
an agent reports being blocked.

A contested path is different. If another agent's claim covers it, that is real
information and the gate should still refuse -- so this only ever grants what is
free. It is the folder guard's `--auto-claim-staged` behaviour, applied to the
board rather than to leases.

Deliberately additive: it widens your claim and never narrows anyone's, so running
it cannot take work away from an agent that is mid-flight.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
CLAIM_TOOL = ROOT / "scripts" / "crew" / "workboard" / "claim.py"


def _staged(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def _claims(board: Path) -> dict[str, list[str]]:
    """Every agent's declared scope, read from the WORKING TREE board.

    The working tree, not the index or HEAD: a claim made seconds ago is real, and
    gates that read a committed snapshot report an agent's own previous scope back
    at them. That mismatch cost two agents most of a day.
    """
    out: dict[str, list[str]] = {}
    try:
        text = board.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        if not line.startswith("- agent="):
            continue
        fields = {}
        for piece in line.lstrip("- ").split(";"):
            if "=" in piece:
                k, v = piece.split("=", 1)
                fields[k.strip()] = v.strip()
        agent = fields.get("agent", "")
        scope = [s.strip().replace("\\", "/") for s in fields.get("scope", "").split(",") if s.strip()]
        if agent:
            out[agent] = scope
    return out


def _covered_by(path: str, scope: list[str]) -> bool:
    for entry in scope:
        if path == entry or path.startswith(entry.rstrip("/") + "/"):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Claim staged paths that no agent holds.")
    ap.add_argument("--agent", required=True)
    ap.add_argument("--task", default="")
    ap.add_argument("--board", default=str(BOARD))
    ap.add_argument("--repo-root", default=str(ROOT))
    ap.add_argument("--paths", nargs="*", default=[], help="Explicit paths; required outside a commit hook.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    board = Path(args.board)

    if not args.paths and not os.environ.get("GIT_INDEX_FILE"):
        # Outside a hook, `git diff --cached` is the SHARED index and contains other
        # agents' in-flight work. Claiming that would take their files, which is the
        # opposite of this tool's purpose. During a pathspec commit git supplies a
        # temp index holding only the files being committed, which is the only set
        # that is safely ours. I made this mistake by hand before adding the guard.
        print("Auto-claim: refusing to read the shared index outside a commit hook.")
        print("            Pass --paths explicitly, or run this as a pre-commit hook.")
        return 0

    staged = [p.strip().replace("\\", "/") for p in args.paths if p.strip()] or _staged(Path(args.repo_root))
    if not staged:
        print("Auto-claim: nothing staged.")
        return 0

    claims = _claims(board)
    mine = claims.get(args.agent, [])
    others = {a: s for a, s in claims.items() if a != args.agent}

    free, contested = [], []
    for path in staged:
        if _covered_by(path, mine):
            continue
        holder = next((a for a, s in others.items() if _covered_by(path, s)), None)
        (contested if holder else free).append((path, holder))

    for path, holder in contested:
        # Named, not silently skipped: the gate is about to refuse over this and the
        # agent deserves to know which peer to talk to.
        print(f"Auto-claim: leaving `{path}` -- held by `{holder}`")

    if not free:
        print("Auto-claim: no free staged paths to add.")
        return 0

    additions = [p for p, _ in free]
    print(f"Auto-claim: adding {len(additions)} uncontested path(s) to `{args.agent}`")
    for path in additions:
        print(f"  + {path}")
    if args.dry_run:
        return 0

    scope = ",".join(dict.fromkeys([*mine, *additions]))
    cmd = [
        sys.executable,
        str(CLAIM_TOOL),
        "--claim",
        "--agent",
        args.agent,
        "--scope",
        scope,
        "--allow-presence-override",
        "--presence-override-reason",
        "auto-claiming staged paths that no other agent holds",
    ]
    if args.task:
        cmd += ["--task", args.task]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        # Never fail a commit over this: it is an unlock, not a gate.
        print(f"Auto-claim: could not widen the claim ({(proc.stderr or proc.stdout or '').strip()[:200]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
