"""Canonical Thomas commit trailers and post-write object verification."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

RESERVED_TRAILERS = (
    "Thomas-Agent",
    "Thomas-Claim",
    "Thomas-Scope",
    "Thomas-Commit-Mode",
    "Thomas-Fallback-Reason",
    "Thomas-Submitted-By",
    "Thomas-Committed-By",
    "Thomas-Submission-Id",
    "Thomas-Gated",
)


class CommitIntegrityError(ValueError):
    """A caller message or created commit violates the Thomas contract."""


def normalize_key(value: str) -> str:
    """Normalize case, whitespace, and punctuation in a trailer key."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


_RESERVED_NORMALIZED = {normalize_key(key): key for key in RESERVED_TRAILERS}


def caller_reserved_lines(message: str) -> list[str]:
    found: list[str] = []
    for line in str(message or "").splitlines():
        candidate = line.strip()
        if ":" not in candidate:
            continue
        key, _value = candidate.split(":", 1)
        if normalize_key(key) in _RESERVED_NORMALIZED:
            found.append(line)
    return found


def validate_caller_message(message: str) -> str:
    body = str(message or "").strip()
    if not body:
        raise CommitIntegrityError("commit message is required")
    forbidden = caller_reserved_lines(body)
    if forbidden:
        raise CommitIntegrityError(
            "caller message contains reserved Thomas trailer(s): " + ", ".join(line.strip() for line in forbidden)
        )
    return body


def compose_message(message: str, trailers: Sequence[tuple[str, str]]) -> str:
    """Append exactly one canonical ordered block of reserved trailers."""
    body = validate_caller_message(message)
    normalized = [normalize_key(key) for key, _value in trailers]
    if len(set(normalized)) != len(normalized):
        raise CommitIntegrityError("generated Thomas trailer keys must be unique")
    unknown = [
        key for (key, _value), norm in zip(trailers, normalized, strict=True) if norm not in _RESERVED_NORMALIZED
    ]
    if unknown:
        raise CommitIntegrityError("unreserved generated trailer key(s): " + ", ".join(unknown))
    rows: list[str] = []
    for key, value in trailers:
        clean_value = str(value or "").strip()
        if not clean_value or "\n" in clean_value or "\r" in clean_value:
            raise CommitIntegrityError(f"invalid generated trailer value for {key}")
        rows.append(f"{_RESERVED_NORMALIZED[normalize_key(key)]}: {clean_value}")
    return body + "\n\n" + "\n".join(rows) + "\n"


def verify_message(message: str, expected_body: str, trailers: Sequence[tuple[str, str]]) -> None:
    canonical = compose_message(expected_body, trailers)
    actual = str(message or "").rstrip("\n") + "\n"
    if actual != canonical:
        raise CommitIntegrityError("created commit message does not equal the canonical message")
    trailer_lines = actual.rstrip("\n").split("\n\n")[-1].splitlines()
    actual_keys = [normalize_key(line.split(":", 1)[0]) for line in trailer_lines if ":" in line]
    expected_keys = [normalize_key(key) for key, _value in trailers]
    if actual_keys != expected_keys or any(actual_keys.count(key) != 1 for key in expected_keys):
        raise CommitIntegrityError("generated Thomas trailers are duplicated or out of order")


@dataclass(frozen=True)
class VerifiedCommit:
    sha: str
    tree: str
    parent: str
    message: str


Runner = Callable[[Path, Sequence[str]], subprocess.CompletedProcess[str]]


def _default_run(repo: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def read_verified_commit(
    repo: Path,
    sha: str,
    *,
    expected_tree: str,
    expected_parent: str,
    expected_body: str,
    expected_trailers: Sequence[tuple[str, str]],
    run: Runner = _default_run,
) -> VerifiedCommit:
    """Read a new object and prove its exact tree, parent, message, and trailers."""
    kind = run(repo, ["cat-file", "-t", sha])
    if kind.returncode != 0 or kind.stdout.strip() != "commit":
        raise CommitIntegrityError("created object is not a readable commit")
    raw = run(repo, ["cat-file", "-p", sha])
    if raw.returncode != 0 or "\n\n" not in raw.stdout:
        raise CommitIntegrityError("created commit object cannot be read back")
    header, message = raw.stdout.split("\n\n", 1)
    trees = [line[5:] for line in header.splitlines() if line.startswith("tree ")]
    parents = [line[7:] for line in header.splitlines() if line.startswith("parent ")]
    if trees != [expected_tree]:
        raise CommitIntegrityError("created commit tree differs from the staged tree")
    if parents != [expected_parent]:
        raise CommitIntegrityError("created commit parent differs from the frozen HEAD")
    verify_message(message, expected_body, expected_trailers)
    return VerifiedCommit(sha=sha, tree=trees[0], parent=parents[0], message=message)
