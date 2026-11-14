"""What the promoter asks the checker, and what the checker answers (spec 2026-10-12, section 8.1).

The checker is its own Windows account, ``thomas-checker``. The promoter (you) writes a job into
``C:\\ProgramData\\ThomasCheck\\jobs``; the checker writes its answer into ``results``, a folder only the checker can
write and the Build teams' account (thomas-agent) cannot even read. Both sides read these files strictly: a file that
is not a small plain JSON object with exactly the expected fields is not a job or an answer, and an answer counts only
for the job it names, field for field. Standard library only: the checker and the promoter both load this file.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

SCHEMA = 1
CHECK = "check"  # before a landing: the change, on the dev it would land on
AFTER = "after"  # after a landing: the window's changes so far, on the dev they made
KINDS = (CHECK, AFTER)
PASSED, FAILED, UNAVAILABLE = "PASSED", "FAILED", "UNAVAILABLE"
VERDICTS = (PASSED, FAILED, UNAVAILABLE)
CHECK_ROOT = Path(r"C:\ProgramData\ThomasCheck")
JOBS, RESULTS, COPIES, STATE = "jobs", "results", "copies", "state"
HEARTBEAT = "heartbeat"
FENCE = "fence.json"
MAX_BYTES = 256 * 1024
MAX_PATHS = 2000
_SHA = re.compile(r"[0-9a-f]{40}")
_ID = re.compile(r"[0-9a-f]{24}")
# A path the promoter lands: plain printable ASCII, no space, quote, backslash or "~", at most 200 long
# (self_change_checks._PLAIN_PATH). A test id adds "::" and the test's name, so it may be longer.
_PATH = re.compile(r"[!#-\[\]-}]{1,200}")
_TEST = re.compile(r"[!#-\[\]-}]{1,400}")


def _texts(value: object, pattern: re.Pattern[str], what: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_PATHS:
        raise ValueError(f"{what} must be a list of at most {MAX_PATHS}")
    if not all(isinstance(item, str) and pattern.fullmatch(item) for item in value):
        raise ValueError(f"every entry of {what} must be plain printable text")
    return tuple(value)


def _sha(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError(f"{key} must be a full commit or tree id")
    return value


def _when(data: dict, key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{key} must be a time")
    return float(value)


@dataclass(frozen=True)
class Job:
    """One check: the commit to test, the dev it is checked against, and the changed files that pick the tests."""

    id: str
    kind: str
    base: str
    commit: str
    tree: str
    changed: tuple[str, ...]
    tests: tuple[str, ...] = ()  # more test files to run beside the selected ones
    posted_at: float = 0.0

    def to_json(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "id": self.id,
            "kind": self.kind,
            "base": self.base,
            "commit": self.commit,
            "tree": self.tree,
            "changed": list(self.changed),
            "tests": list(self.tests),
            "posted_at": self.posted_at,
        }

    @classmethod
    def parse(cls, data: object) -> Job:
        expected = {"schema", "id", "kind", "base", "commit", "tree", "changed", "tests", "posted_at"}
        if not isinstance(data, dict) or set(data) != expected or data.get("schema") != SCHEMA:
            raise ValueError("not a job of this schema")
        if not isinstance(data["id"], str) or not _ID.fullmatch(data["id"]) or data["kind"] not in KINDS:
            raise ValueError("a job has a 24-character id and a known kind")
        return cls(
            data["id"],
            data["kind"],
            _sha(data, "base"),
            _sha(data, "commit"),
            _sha(data, "tree"),
            _texts(data["changed"], _PATH, "changed"),
            _texts(data["tests"], _TEST, "tests"),
            _when(data, "posted_at"),
        )


@dataclass(frozen=True)
class Result:
    """The checker's answer to one job. ``findings`` are the tests that fail alone with the change and not without
    it; ``failed`` is every test that failed in the full run, explained or not. ``ran`` is how many test files ran and
    ``seen`` how many tests their reports hold: a PASSED with no test seen proves nothing (2026-10-14 review, B3)."""

    job: str
    kind: str
    base: str
    commit: str
    tree: str
    verdict: str
    why: str = ""
    ran: int = 0
    failed: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()
    boot: str = ""
    finished_at: float = 0.0
    seen: int = 0

    def answers(self, job: Job) -> bool:
        """True only when this answer is for exactly *job*: its id, kind, base, commit and tree."""
        return (self.job, self.kind, self.base, self.commit, self.tree) == (
            job.id,
            job.kind,
            job.base,
            job.commit,
            job.tree,
        )

    def to_json(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "job": self.job,
            "kind": self.kind,
            "base": self.base,
            "commit": self.commit,
            "tree": self.tree,
            "verdict": self.verdict,
            "why": self.why,
            "ran": self.ran,
            "failed": list(self.failed),
            "findings": list(self.findings),
            "boot": self.boot,
            "finished_at": self.finished_at,
            "seen": self.seen,
        }

    @classmethod
    def parse(cls, data: object) -> Result:
        expected = {"schema", "job", "kind", "base", "commit", "tree", "verdict", "why", "ran", "failed", "findings"}
        expected |= {"boot", "finished_at", "seen"}
        if not isinstance(data, dict) or set(data) != expected or data.get("schema") != SCHEMA:
            raise ValueError("not an answer of this schema")
        if not isinstance(data["job"], str) or not _ID.fullmatch(data["job"]) or data["kind"] not in KINDS:
            raise ValueError("an answer names a 24-character job id and a known kind")
        if data["verdict"] not in VERDICTS or not isinstance(data["why"], str) or not isinstance(data["boot"], str):
            raise ValueError("an answer's verdict is PASSED, FAILED or UNAVAILABLE, with words")
        if any(type(data[key]) is not int or data[key] < 0 for key in ("ran", "seen")):
            raise ValueError("ran and seen are counts")
        return cls(
            data["job"],
            data["kind"],
            _sha(data, "base"),
            _sha(data, "commit"),
            _sha(data, "tree"),
            data["verdict"],
            data["why"][:2000],
            data["ran"],
            _texts(data["failed"], _TEST, "failed"),
            _texts(data["findings"], _TEST, "findings"),
            data["boot"][:2000],
            _when(data, "finished_at"),
            data["seen"],
        )


def read_json(path: Path, limit: int = MAX_BYTES) -> object | None:
    """The JSON in *path*: None when there is no such file; ValueError when it is not a plain file of at most *limit*
    bytes holding JSON. A link, a folder or a device is never read."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
        raise ValueError(f"{Path(path).name} is not a plain file of at most {limit} bytes")
    raw = Path(path).read_bytes()
    if len(raw) > limit:
        raise ValueError(f"{Path(path).name} grew past {limit} bytes")
    return json.loads(raw.decode("utf-8"), parse_constant=_no_constant, object_pairs_hook=_no_repeats)


def _no_constant(name: str) -> object:
    raise ValueError(f"{name} is not a number")


def _no_repeats(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("a key is repeated")
    return dict(pairs)


def write_json(path: Path, data: dict[str, object]) -> None:
    """Write *data* whole: a temporary file beside it, then a rename, so a reader never sees half of it."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(json.dumps(data, indent=1, sort_keys=True).encode("utf-8"))
    os.replace(tmp, path)


__all__ = [
    "AFTER",
    "CHECK",
    "CHECK_ROOT",
    "COPIES",
    "FAILED",
    "FENCE",
    "HEARTBEAT",
    "JOBS",
    "KINDS",
    "PASSED",
    "RESULTS",
    "SCHEMA",
    "STATE",
    "UNAVAILABLE",
    "Job",
    "Result",
    "read_json",
    "write_json",
]
