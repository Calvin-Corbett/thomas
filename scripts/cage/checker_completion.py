"""A checker answer counts only after its matching completion receipt is published.

The service writes the result first and the receipt last, after its test processes have ended. Both hashes bind the
whole job and answer, so a result left before a job runs, or replaced after completion, is never accepted on its own.
This protocol requires the result and state folders to be protected from the test identity. That identity split is in
place (review B1): tests run as ``thomas-runner``, which enable_window.ps1 gives no write on ``results`` or ``state``
(scripts/cage/checker_runner.py). These hashes detect replacements; the ACL, not a hash, is the identity boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path

from scripts.cage import checker_jobs as cj

COMPLETED = "completed"
SCHEMA = 1
_HASH = re.compile(r"[0-9a-f]{64}")


def result_path(root: Path, job: cj.Job) -> Path:
    return Path(root) / cj.RESULTS / f"{job.id}.json"


def receipt_path(root: Path, job: cj.Job) -> Path:
    return Path(root) / cj.STATE / COMPLETED / f"{job.id}.json"


def _digest(data: object) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _receipt(job: cj.Job, raw: object) -> dict[str, object]:
    canonical_job = cj.Job.parse(job.to_json()).to_json()
    return {"schema": SCHEMA, "job": job.id, "job_sha256": _digest(canonical_job), "result_sha256": _digest(raw)}


def _validate_receipt(raw: object) -> None:
    if not isinstance(raw, dict) or set(raw) != {"schema", "job", "job_sha256", "result_sha256"}:
        raise ValueError("the checker's completion receipt is not one")
    if type(raw["schema"]) is not int or raw["schema"] != SCHEMA or not isinstance(raw["job"], str):
        raise ValueError("the checker's completion receipt has another schema")
    if any(not isinstance(raw[key], str) or not _HASH.fullmatch(raw[key]) for key in ("job_sha256", "result_sha256")):
        raise ValueError("the checker's completion receipt has no complete hashes")


def read(root: Path, job: cj.Job) -> cj.Result | None:
    """A completed answer, None while unfinished, or ValueError for damaged or replaced evidence."""
    answer_file, done_file = result_path(root, job), receipt_path(root, job)
    raw = cj.read_json(answer_file)
    receipt = cj.read_json(done_file)
    if raw is None:
        if receipt is not None:
            raise ValueError("the checker's completed answer is missing")
        return None
    answer = cj.Result.parse(raw)
    if not answer.answers(job):
        raise ValueError("the checker's answer is for another job, commit or tree")
    if receipt is None:
        return None
    _validate_receipt(receipt)
    if receipt != _receipt(job, raw):
        raise ValueError("the checker's answer does not match its completion receipt")
    # Never combine an old answer with a new receipt, or an answer replaced during these reads.
    if cj.read_json(answer_file) != raw or cj.read_json(done_file) != receipt:
        raise ValueError("the checker's answer changed while it was read")
    return answer


def publish(root: Path, job: cj.Job, answer: cj.Result) -> cj.Result:
    """Publish the service's answer, then acknowledge completion. The caller must first end its test processes."""
    answer = cj.Result.parse(answer.to_json())
    if not answer.answers(job):
        raise ValueError("the checker cannot finish another job's answer")
    raw = answer.to_json()
    answer_file, done_file = result_path(root, job), receipt_path(root, job)
    answer_file.parent.mkdir(parents=True, exist_ok=True)
    done_file.parent.mkdir(parents=True, exist_ok=True)
    cj.write_json(answer_file, raw)
    cj.write_json(done_file, _receipt(job, raw))
    return answer


def unchanged(
    job: cj.Job,
    accepted: cj.Result,
    read_result: Callable[[cj.Job], cj.Result | None],
    *,
    clock: Callable[[], float] = time.time,
) -> cj.Result:
    """Read an accepted answer again immediately before acting; any replacement or disappearance is unavailable."""
    current = read_result(job)
    if current == accepted and current.answers(job):
        return current
    return cj.Result(
        job.id,
        job.kind,
        job.base,
        job.commit,
        job.tree,
        cj.UNAVAILABLE,
        "the checker's completed answer changed or disappeared after it was read",
        finished_at=clock(),
    )


__all__ = ["COMPLETED", "publish", "read", "receipt_path", "result_path", "unchanged"]
