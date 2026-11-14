"""Run N scripted workers against one repository and report what survived.

The question this answers is narrow on purpose: when N agents each commit their
own disjoint work to one checkout, does all of it land? Every worker edits a path
no other worker touches, so a missing file is the coordination layer losing work,
never two workers disagreeing about content.

Reports throughput separately from the number of workers launched, because those
are different numbers and only one of them is an achievement. Twenty workers that
all wait behind one lock is not twenty agents working.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve()
WORKER = HERE.parent / "worker.py"


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def make_repo(root: Path) -> Path:
    """A disposable repository. Never the repo under development."""
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", "main"], cwd=root)
    _run(["git", "config", "user.email", "swarm@test"], cwd=root)
    _run(["git", "config", "user.name", "swarm"], cwd=root)
    (root / "README.md").write_text("swarm harness fixture\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=root)
    _run(["git", "commit", "-qm", "seed"], cwd=root)
    return root


def _isolate(repo: Path, workers: int, arena: Path) -> tuple[list[Path], list[str]]:
    """Give every worker its own worktree and its own branch.

    Two separate resources are being un-shared here, and they fix two separate
    failures measured at 20 workers in shared mode. The private INDEX fixes
    `pathspec did not match any file(s) known to git` -- a commit rewrites the whole
    index, so one worker's commit silently discarded another's completed `git add`.
    The private BRANCH fixes `cannot lock ref HEAD: is at X but expected Y` -- ref
    updates are compare-and-swap, so concurrent commits to one branch make losers.
    Worktrees alone would fix only the first.
    """
    trees: list[Path] = []
    errors: list[str] = []
    arena.mkdir(parents=True, exist_ok=True)
    for i in range(workers):
        wid = f"w{i:03d}"
        wt = arena / wid
        proc = _run(["git", "worktree", "add", "-q", "-b", f"swarm/{wid}", str(wt), "main"], cwd=repo)
        if proc.returncode != 0:
            why = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()
            errors.append(f"worktree add {wid}: {why[0] if why else 'no output'}")
            continue
        trees.append(wt)
    return trees, errors


def _integrate(repo: Path, workers: int) -> list[str]:
    """Land every branch on main, one at a time. Returns branches that failed.

    Serial by necessity: main has one head and merges are ordered. This is the step
    a real merge queue would batch and speculate over, and it is where the next
    ceiling lives once the shared index is gone.
    """
    failed = []
    for i in range(workers):
        branch = f"swarm/w{i:03d}"
        proc = _run(["git", "merge", "--no-edit", branch], cwd=repo)
        if proc.returncode != 0:
            # Say WHY. A step that reports failure without a reason is the same
            # defect as one that reports success without checking.
            why = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()
            failed.append(f"{branch}: {why[0] if why else 'no output'}")
    return failed


def run_swarm(repo: Path, workers: int, edits: int, out_dir: Path, isolation: str = "shared") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    trees: list[Path] = []
    setup_errors: list[str] = []
    if isolation == "worktree":
        trees, setup_errors = _isolate(repo, workers, out_dir.parent / "trees")
        if setup_errors:
            # Refuse to run rather than quietly measure a different configuration.
            # An earlier version of this harness swallowed worktree-add failures and
            # printed `isolation: worktree` over a shared-index run -- a harness that
            # misreports its own setup produces numbers worse than no numbers.
            return {
                "workers": workers,
                "edits_each": edits,
                "intended": 0,
                "claimed_committed": 0,
                "actually_in_tree": 0,
                "lost": [],
                "failures": setup_errors,
                "wall_seconds": 0.0,
                "commits_per_second": 0,
                "os_processes": workers,
                "isolation": isolation,
                "merge_failures": [],
                "setup_failed": True,
            }

    start_at = time.time() + 2.0  # a barrier so they genuinely overlap
    began = time.time()

    def launch(i: int) -> None:
        wid = f"w{i:03d}"
        where = trees[i] if trees else repo
        _run(
            [
                sys.executable,
                str(WORKER),
                "--repo",
                str(where),
                "--worker-id",
                wid,
                "--out",
                str(out_dir / f"{wid}.json"),
                "--edits",
                str(edits),
                "--start-at",
                f"{start_at:.6f}",
            ]
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(launch, range(workers)))

    wall = time.time() - began - 2.0
    merge_failures: list[str] = []
    if isolation == "worktree":
        merge_began = time.time()
        merge_failures = _integrate(repo, workers)
        wall += time.time() - merge_began

    results = []
    for f in sorted(out_dir.glob("w*.json")):
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            results.append({"worker": f.stem, "committed": 0, "failures": ["no result file"], "files": []})

    # The verdict is not "did the commands succeed" but "is the work in the tree".
    tracked = set(_run(["git", "ls-files"], cwd=repo).stdout.split())
    intended = {f"work/w{i:03d}/file_{n}.txt" for i in range(workers) for n in range(edits)}
    landed = intended & tracked

    return {
        "workers": workers,
        "edits_each": edits,
        "intended": len(intended),
        "claimed_committed": sum(r.get("committed", 0) for r in results),
        "actually_in_tree": len(landed),
        "lost": sorted(intended - tracked),
        "failures": [f for r in results for f in r.get("failures", [])],
        "wall_seconds": round(wall, 2),
        "commits_per_second": round(len(landed) / wall, 2) if wall > 0 else 0,
        "os_processes": workers,
        "isolation": isolation,
        "merge_failures": merge_failures,
        "setup_failed": False,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Measure whether N concurrent workers all land their work.")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--edits", type=int, default=3)
    ap.add_argument("--root", required=True, help="Disposable directory; contents are created here.")
    ap.add_argument("--isolation", choices=["shared", "worktree"], default="shared")
    args = ap.parse_args(argv)

    root = Path(args.root)
    repo = make_repo(root / "repo")
    report = run_swarm(repo, args.workers, args.edits, root / "results", isolation=args.isolation)

    ok = report["actually_in_tree"] == report["intended"] and not report["lost"]
    print(json.dumps(report, indent=2)[:2000])
    print()
    print(f"  isolation          : {report['isolation']}")
    print(f"  workers launched   : {report['workers']}  ({report['os_processes']} OS processes)")
    print(f"  work intended      : {report['intended']}")
    print(f"  work in the tree   : {report['actually_in_tree']}")
    print(f"  LOST               : {len(report['lost'])}")
    print(f"  wall seconds       : {report['wall_seconds']}")
    print(f"  throughput         : {report['commits_per_second']} commits/sec")
    print(f"  VERDICT            : {'PASS - nothing lost' if ok else 'FAIL - work went missing'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
