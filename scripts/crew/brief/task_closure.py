"""Finish one claimed task without sweeping another agent's working files.

The existing scoped commit tool owns staging and gate execution. This module
only orders the final steps: commit, read back the claim's dirty paths, record
commit evidence on the task, then release the claim. Any failed step holds the
claim and returns an explicit blocker.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.brief import commit
from scripts.crew.tasks import manager
from scripts.crew.workboard import claim


@dataclass(frozen=True)
class ClosureResult:
    ok: bool
    stage: str
    message: str
    commit_sha: str = ""
    remaining_paths: tuple[str, ...] = ()


def finish_claimed_task(
    *,
    agent: str,
    task_id: str,
    message: str,
    repo_root: Path = commit.ROOT,
    workboard_path: Path = commit.DEFAULT_WORKBOARD,
    include_paths: Sequence[str] = (),
    allow_presence_override: bool = False,
    presence_override_reason: str = "",
) -> ClosureResult:
    """Create a scoped commit and finish only after its claimed files are clean."""
    if not str(task_id).strip() or not str(message).strip():
        return ClosureResult(False, "input", "task id and commit message are required")

    started = datetime.now(timezone.utc)
    result = commit.commit_scoped_changes(
        message=f"{message.strip()}\n\nTask: {task_id.strip()}",
        agent=agent,
        include_paths=include_paths,
        repo_root=repo_root,
        workboard_path=workboard_path,
    )
    if not result.ok or not result.commit_sha:
        return ClosureResult(False, "commit", result.message or "scoped commit did not land")

    try:
        dirty = commit._parse_status_paths(repo_root)
    except (OSError, RuntimeError, ValueError) as exc:
        return ClosureResult(False, "readback", f"could not read Git status after commit: {exc}", result.commit_sha)
    remaining = tuple(
        path for path in dirty if any(commit._scope_matches_path(scope, path) for scope in result.claim_scopes)
    )
    if remaining:
        return ClosureResult(
            False,
            "remaining_work",
            "claimed files remain uncommitted; task stays open",
            result.commit_sha,
            remaining,
        )

    ok_review, review = manager.set_task_status(
        workboard_path, task_id=task_id, status="review", actor=agent, enforce_transition=True
    )
    if not ok_review:
        return ClosureResult(False, "review", str(review), result.commit_sha)
    ok_done, done = manager.set_task_status(
        workboard_path,
        task_id=task_id,
        status="done",
        actor=agent,
        enforce_transition=True,
        evidence=f"commit:{result.commit_sha}",
        evidence_not_before=started,
    )
    if not ok_done:
        return ClosureResult(False, "evidence", str(done), result.commit_sha)

    ok_release, release = claim.release(
        workboard_path,
        agent=agent,
        require_done_state=True,
        allow_presence_override=allow_presence_override,
        presence_override_reason=presence_override_reason,
    )
    if not ok_release:
        return ClosureResult(False, "release", str(release), result.commit_sha)
    return ClosureResult(True, "done", "task committed, evidenced, and claim released", result.commit_sha)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Commit and close one claimed Thomas task.")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--allow-presence-override", action="store_true")
    parser.add_argument("--presence-override-reason", default="")
    args = parser.parse_args(argv)
    result = finish_claimed_task(
        agent=args.agent,
        task_id=args.task_id,
        message=args.message,
        include_paths=args.include,
        allow_presence_override=args.allow_presence_override,
        presence_override_reason=args.presence_override_reason,
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
