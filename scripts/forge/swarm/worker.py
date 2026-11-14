"""One scripted worker. No model calls: this measures coordination, not intelligence.

Each worker edits a file nobody else touches, so any work that goes missing is the
coordination layer losing it rather than two workers overwriting each other. That
separation is the whole point -- a harness where workers genuinely conflict cannot
tell a lock bug from a merge decision.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LOCK_WAIT_SECONDS = 30.0


def _git(repo: Path, *args: str, retries: int = 40) -> tuple[int, str]:
    """Run git, waiting out `index.lock` rather than failing on it.

    A partial `git add` is the specific damage the shared index does: the command
    fails halfway, the change stays unstaged, and the commit then runs against a
    tree the agent never had. Counting those waits is a measurement, not a
    workaround -- `lock_waits` in the result is how we see contention.
    """
    waits = 0
    for _ in range(retries):
        if (repo / ".git" / "index.lock").exists():
            waits += 1
            time.sleep(0.25)
            continue
        proc = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if proc.returncode == 0 or "index.lock" not in (proc.stderr or ""):
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        waits += 1
        time.sleep(0.25)
    return 1, f"gave up after {waits} lock waits"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--worker-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--edits", type=int, default=1)
    ap.add_argument("--start-at", type=float, default=0.0, help="Unix time to begin, so workers truly overlap.")
    args = ap.parse_args(argv)

    repo = Path(args.repo)
    wid = args.worker_id
    result = {"worker": wid, "committed": 0, "failures": [], "lock_waits": 0, "files": []}

    # A barrier, not a stagger: workers that start seconds apart never contend, and
    # a harness that cannot produce contention cannot prove its absence.
    while time.time() < args.start_at:
        time.sleep(0.01)

    began = time.time()
    for n in range(args.edits):
        rel = f"work/{wid}/file_{n}.txt"
        body = f"{wid} edit {n} at {time.time():.6f}\n"
        try:
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        except OSError as exc:
            result["failures"].append(f"write {rel}: {exc}")
            continue

        code, out = _git(repo, "add", "--", rel)
        if code != 0:
            result["failures"].append(f"add {rel}: {out.strip()[:160]}")
            continue
        code, out = _git(
            repo,
            "-c",
            f"user.name={wid}",
            "-c",
            f"user.email={wid}@swarm.test",
            "commit",
            "-q",
            "--no-verify",
            "-m",
            f"{wid}: edit {n}",
            "--",
            rel,
        )
        if code != 0:
            result["failures"].append(f"commit {rel}: {out.strip()[:160]}")
            continue
        result["committed"] += 1
        result["files"].append(rel)

    result["seconds"] = round(time.time() - began, 3)
    result["pid"] = os.getpid()
    Path(args.out).write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
