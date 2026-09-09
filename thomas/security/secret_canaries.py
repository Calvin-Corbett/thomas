"""Secret canaries: planted sentinel secrets and a zero-occurrence sweep (CAP-089).

This module sits beside the redaction layer (``thomas.policy.redact`` /
``thomas.server.audit_log``); it does not modify it.  A *canary* is an
unmistakable, greppable sentinel token (``THOMAS-CANARY-<label>-<10 hex>``)
that is deliberately pushed through real pathways (tool calls, audit writes).
Because the token is never a real secret and never appears literally in source
code, ANY occurrence of a registered canary in persisted artifacts — code,
logs, transcripts, memory stores — proves a leak in the redaction pipeline.

Design notes:

- Minting is deterministic (seeded SHA-256, no randomness at import time), so
  the same label always yields the same token across processes.
- The sweep streams files in bounded chunks (never loads a whole file), skips
  ``.git`` / ``.venv`` / ``node_modules`` style directories and oversized
  files, and byte-scans binary stores (e.g. sqlite audit DBs) safely — a
  canary that leaked into a sqlite page is still found.
- The canary registry file itself necessarily contains the tokens; the sweep
  always excludes it so the registry never counts as a leak.
- ``CANARY_PATTERN`` can be handed to ``Redactor(additional_patterns=[...])``
  to make the redaction pipeline canary-aware.

CLI: ``python -m thomas.security.secret_canaries --sweep [paths...]`` prints a
JSON report and exits 0 on zero occurrences, 1 on any hit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CANARY_PREFIX = "THOMAS-CANARY"
#: Regex (string form) matching any minted canary token; safe to register as a
#: redaction pattern via ``Redactor(additional_patterns=[CANARY_PATTERN])``.
CANARY_PATTERN = rf"{CANARY_PREFIX}-[A-Za-z0-9][A-Za-z0-9_.\-]{{0,63}}-[0-9a-f]{{10}}"
CANARY_RE = re.compile(CANARY_PATTERN)

REGISTRY_ENV = "THOMAS_CANARY_REGISTRY_PATH"
_RUNTIME_DIR_ENV = "THOMAS_RUNTIME_DIR"
_REGISTRY_VERSION = 1

_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
_MINT_SEED = "thomas-cap089-secret-canary-v1"
_DIGEST_HEX_LEN = 10

DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
_CHUNK_SIZE = 1 << 20  # 1 MiB streaming chunks

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        ".tox",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".idea",
        ".vscode",
    }
)

#: Repo-relative roots covering code, logs, transcript and memory stores.
DEFAULT_SWEEP_ROOTS: tuple[str, ...] = ("thomas", "tests", "scripts", "runtime")


class CanaryError(ValueError):
    """Raised for invalid canary labels or malformed registry contents."""


# ---------------------------------------------------------------------------
# Minting and registry
# ---------------------------------------------------------------------------


def mint_canary(label: str) -> str:
    """Deterministically mint a canary token for *label*.

    The suffix is derived from a seeded SHA-256 hash — no randomness, so tests
    and CI mint identical tokens for identical labels.
    """
    if not _LABEL_RE.match(label or ""):
        raise CanaryError(f"invalid canary label {label!r}: must match {_LABEL_RE.pattern}")
    digest = hashlib.sha256(f"{_MINT_SEED}:{label}".encode()).hexdigest()
    return f"{CANARY_PREFIX}-{label}-{digest[:_DIGEST_HEX_LEN]}"


def registry_path(override: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the canary registry path (env-overridable for tests)."""
    if override is not None:
        return Path(override)
    env_override = os.environ.get(REGISTRY_ENV, "").strip()
    if env_override:
        return Path(env_override)
    runtime_dir = Path(os.environ.get(_RUNTIME_DIR_ENV, "").strip() or "runtime")
    return runtime_dir / "security" / "secret_canaries.json"


def load_registry(path: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """Load the label -> token registry; missing file means empty registry."""
    reg_path = registry_path(path)
    try:
        raw = reg_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("canary registry unreadable at %s: %s", reg_path, exc)
        raise
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CanaryError(f"canary registry at {reg_path} is not valid JSON: {exc}") from exc
    canaries = data.get("canaries") if isinstance(data, dict) else None
    if not isinstance(canaries, dict):
        raise CanaryError(f"canary registry at {reg_path} has no 'canaries' object")
    out: dict[str, str] = {}
    for label, token in canaries.items():
        if isinstance(label, str) and isinstance(token, str) and CANARY_RE.fullmatch(token):
            out[label] = token
    return out


def register_canary(label: str, path: str | os.PathLike[str] | None = None) -> str:
    """Mint the canary for *label* and persist it in the registry (idempotent)."""
    token = mint_canary(label)
    reg_path = registry_path(path)
    registry = load_registry(reg_path) if reg_path.exists() else {}
    if registry.get(label) == token:
        return token
    registry[label] = token
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": _REGISTRY_VERSION, "canaries": registry}
    tmp_path = reg_path.with_suffix(reg_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, reg_path)
    return token


def plant_canary_secret(
    store_callable: Callable[[str], Any],
    label: str = "planted",
    path: str | os.PathLike[str] | None = None,
) -> str:
    """Register a canary and push it through a REAL storage pathway.

    *store_callable* receives the freshly minted token and is expected to feed
    it through a genuine pipeline (a guarded tool call, an audit-log write, a
    memory store append).  A subsequent :func:`sweep` over the persisted
    artifacts then proves whether the redaction pipeline kept it out.
    """
    token = register_canary(label, path)
    store_callable(token)
    return token


# ---------------------------------------------------------------------------
# Sweep engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CanaryHit:
    """A single canary occurrence: which token, where, and on which line."""

    canary: str
    label: str
    location: str
    line_no: int


@dataclass
class SweepReport:
    """Structured result of a sweep across code, logs, transcripts, memory."""

    canary_count: int
    hits: list[CanaryHit] = field(default_factory=list)
    files_scanned: int = 0
    files_skipped: int = 0
    roots: tuple[str, ...] = ()

    @property
    def zero_occurrences(self) -> bool:
        return not self.hits

    def to_dict(self) -> dict[str, Any]:
        # Deliberately excludes the token values except inside hits: a clean
        # report may itself be persisted to logs and must not seed new hits.
        return {
            "canary_count": self.canary_count,
            "zero_occurrences": self.zero_occurrences,
            "files_scanned": self.files_scanned,
            "files_skipped": self.files_skipped,
            "roots": list(self.roots),
            "hits": [asdict(hit) for hit in self.hits],
        }


def _iter_files(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIR_NAMES)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def _scan_file_for_tokens(
    path: Path, tokens: dict[bytes, tuple[str, str]], chunk_size: int = _CHUNK_SIZE
) -> list[tuple[str, str, int]]:
    """Stream *path* in bounded chunks; return (token_text, line_no) per token.

    Binary-safe: canary tokens are pure ASCII, so a byte-level substring scan
    finds them inside text logs and binary stores (sqlite pages) alike.  Only
    the first occurrence per token per file is reported.  Line numbers are
    1-based newline counts (best-effort for binary content).
    """
    found: list[tuple[str, str, int]] = []
    remaining = dict(tokens)
    overlap = max(len(t) for t in remaining) - 1 if remaining else 0
    carry = b""
    line_base = 1
    with path.open("rb") as handle:
        while remaining:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            window = carry + chunk
            for token_bytes in list(remaining):
                idx = window.find(token_bytes)
                if idx != -1:
                    line_no = line_base + window.count(b"\n", 0, idx)
                    label, token = remaining.pop(token_bytes)
                    found.append((label, token, line_no))
            keep = window[-overlap:] if overlap else b""
            consumed = len(window) - len(keep)
            line_base += window.count(b"\n", 0, consumed)
            carry = keep
    return found


def sweep(
    paths: Iterable[str | os.PathLike[str]],
    canaries: dict[str, str] | None = None,
    registry: str | os.PathLike[str] | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> SweepReport:
    """Scan *paths* (files, code dirs, log/transcript/memory stores) for every
    registered canary token and report each occurrence with its location.

    ``canaries`` defaults to the persisted registry.  The registry file itself
    is always excluded — it legitimately contains every token.
    """
    active = dict(canaries) if canaries is not None else load_registry(registry)
    token_map = {token.encode("ascii"): (label, token) for label, token in active.items()}
    registry_file = registry_path(registry).resolve()

    roots = [Path(p) for p in paths]
    report = SweepReport(canary_count=len(active), roots=tuple(str(p) for p in roots))
    if not token_map:
        return report

    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for file_path in _iter_files(root):
            resolved = file_path.resolve()
            if resolved in seen or resolved == registry_file:
                continue
            seen.add(resolved)
            try:
                size = file_path.stat().st_size
            except OSError as exc:
                logger.warning("canary sweep cannot stat %s: %s", file_path, exc)
                report.files_skipped += 1
                continue
            if size > max_file_bytes:
                report.files_skipped += 1
                continue
            try:
                matches = _scan_file_for_tokens(file_path, token_map)
            except OSError as exc:
                logger.warning("canary sweep cannot read %s: %s", file_path, exc)
                report.files_skipped += 1
                continue
            report.files_scanned += 1
            for label, token, line_no in matches:
                report.hits.append(CanaryHit(canary=token, label=label, location=str(file_path), line_no=line_no))
    return report


def default_sweep_paths(base: str | os.PathLike[str] | None = None) -> list[Path]:
    """Existing default roots (code, logs, transcripts, memory) under *base*."""
    base_path = Path(base) if base is not None else Path.cwd()
    return [base_path / root for root in DEFAULT_SWEEP_ROOTS if (base_path / root).exists()]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m thomas.security.secret_canaries",
        description="Mint secret canaries and sweep artifacts for zero occurrences.",
    )
    parser.add_argument("--sweep", action="store_true", help="run the zero-occurrence sweep")
    parser.add_argument("--mint", metavar="LABEL", help="mint and register a canary for LABEL")
    parser.add_argument("--registry", help="override the canary registry path")
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=DEFAULT_MAX_FILE_BYTES,
        help="skip files larger than this many bytes (default 10 MiB)",
    )
    parser.add_argument("paths", nargs="*", help="files/dirs to sweep (default: repo roots)")
    args = parser.parse_args(argv)

    if args.mint:
        token = register_canary(args.mint, args.registry)
        print(json.dumps({"label": args.mint, "canary": token, "registry": str(registry_path(args.registry))}))
        return 0

    if not args.sweep:
        parser.error("nothing to do: pass --sweep and/or --mint LABEL")

    paths = [Path(p) for p in args.paths] if args.paths else default_sweep_paths()
    report = sweep(paths, registry=args.registry, max_file_bytes=args.max_file_bytes)
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.zero_occurrences else 1


if __name__ == "__main__":
    sys.exit(main())
