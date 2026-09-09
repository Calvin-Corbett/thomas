#!/usr/bin/env python3
"""Bible drift detection (Crew.Forge — Tier 7 Phase A substrate).

Scans a markdown bible (default ``docs/THOMAS_BIBLE.md``) for stamped sections,
computes the current SHA-256 of each section's ``covers`` paths, and reports
sections where the stamped hash diverges from the on-disk hash.

Stamp protocol
--------------

Each section can carry a single-line stamp immediately after the ``## Section
N. Title`` heading. The stamp is a blockquote so it renders as a callout and
is easy to grep::

    > Stamp: covers=[path/one.py,path/two/] hash=sha256:abc123... status=green depth=DEEP

Fields:

- ``covers`` — comma-separated list of repo-relative paths the section
  describes. Paths can be files or directories. Missing paths count as drift.
- ``hash`` — ``sha256:<hex>`` of the canonical concatenation of all covered
  paths (see :func:`compute_covers_hash`). Re-run this script with ``--update``
  (planned) to refresh stamps after intentional edits.
- ``status`` — one of ``green`` (verified, hash matches), ``yellow`` (suspected
  drift, manual audit needed), ``red`` (known stale, do not trust). This
  script only reads ``status``; promotion happens elsewhere (Phase B).
- ``depth`` — ``DEEP``, ``SAMPLE``, ``CATALOG``, etc. Free-form for now.

The script reports three buckets:

- ``green_drifted`` — section says green, but on-disk hash differs. Promote
  to yellow.
- ``yellow_or_red`` — section already marked stale; just surface.
- ``missing_paths`` — section covers paths that don't exist on disk.
- ``unstamped`` — section has no stamp. Reported but not blocking.

Exit code is 0 unless ``--strict`` is passed AND green sections drifted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = _REPO_ROOT
DEFAULT_BIBLE = ROOT / "docs" / "THOMAS_BIBLE.md"

SECTION_HEADING_RE = re.compile(r"^##\s+(?P<title>\S.*?)\s*$", re.MULTILINE)
STAMP_RE = re.compile(
    r"^>\s*Stamp:\s*"
    r"(?:.*?\bcovers=\[(?P<covers>[^\]]*)\])?"
    r"(?:.*?\bhash=sha256:(?P<hash>[a-fA-F0-9]+))?"
    r"(?:.*?\bstatus=(?P<status>green|yellow|red))?"
    r"(?:.*?\bdepth=(?P<depth>\w+))?.*$",
    re.MULTILINE,
)


@dataclass
class StampedSection:
    title: str
    line_no: int
    covers: list[str] = field(default_factory=list)
    stamped_hash: str = ""
    status: str = ""
    depth: str = ""
    current_hash: str = ""
    missing_paths: list[str] = field(default_factory=list)
    drifted: bool = False


def _normalize_path(value: str) -> str:
    return value.strip().replace("\\", "/").rstrip("/")


def _iter_covered_files(repo_root: Path, covers: list[str]) -> tuple[list[Path], list[str]]:
    """Resolve covers paths to a deterministic file list + missing list."""
    files: list[Path] = []
    missing: list[str] = []
    for raw in covers:
        rel = _normalize_path(raw)
        if not rel:
            continue
        target = (repo_root / rel).resolve()
        try:
            target.relative_to(repo_root.resolve())
        except ValueError:
            missing.append(rel)
            continue
        if not target.exists():
            missing.append(rel)
            continue
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            for path in sorted(target.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    files.append(path)
    return files, missing


def compute_covers_hash(repo_root: Path, covers: list[str]) -> tuple[str, list[str]]:
    """Hash the canonical contents of ``covers`` paths.

    Each file contributes ``<repo-relative-path>\\n<sha256-of-bytes>\\n`` to a
    rolling SHA-256. Returns ``(hex_digest, missing_paths)``.
    """
    files, missing = _iter_covered_files(repo_root, covers)
    hasher = hashlib.sha256()
    repo_root_resolved = repo_root.resolve()
    for path in sorted(files):
        try:
            rel = path.relative_to(repo_root_resolved).as_posix()
        except ValueError:
            rel = path.as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\n")
        try:
            with path.open("rb") as fh:
                file_hash = hashlib.sha256(fh.read()).hexdigest()
            hasher.update(file_hash.encode("ascii"))
            hasher.update(b"\n")
        except OSError as exc:
            missing.append(f"{rel}: {exc}")
    return hasher.hexdigest(), missing


def parse_bible(bible_path: Path) -> tuple[list[StampedSection], list[dict[str, object]]]:
    """Return (stamped sections, unstamped section summaries)."""
    if not bible_path.exists():
        return [], []
    text = bible_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    sections: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        match = re.match(r"^##\s+(?P<title>\S.*?)\s*$", line)
        if match:
            sections.append((idx, match.group("title")))
    stamped: list[StampedSection] = []
    unstamped: list[dict[str, object]] = []
    for i, (line_no, title) in enumerate(sections):
        # Look for stamp within the next 6 lines (after heading, blank, optional verified line)
        window_end = min(line_no + 8, len(lines))
        stamp_match = None
        for probe_line in lines[line_no + 1 : window_end]:
            stamp_match = STAMP_RE.match(probe_line)
            if stamp_match and stamp_match.group("covers"):
                break
            stamp_match = None
        if stamp_match is None:
            unstamped.append({"title": title, "line_no": line_no + 1})
            continue
        covers_raw = stamp_match.group("covers") or ""
        covers_list = [_normalize_path(item) for item in covers_raw.split(",") if item.strip()]
        stamped.append(
            StampedSection(
                title=title,
                line_no=line_no + 1,
                covers=covers_list,
                stamped_hash=stamp_match.group("hash") or "",
                status=(stamp_match.group("status") or "").lower(),
                depth=(stamp_match.group("depth") or "").upper(),
            )
        )
    return stamped, unstamped


def evaluate_drift(repo_root: Path, sections: list[StampedSection]) -> list[StampedSection]:
    for section in sections:
        section.current_hash, section.missing_paths = compute_covers_hash(repo_root, section.covers)
        if section.stamped_hash and section.current_hash != section.stamped_hash:
            section.drifted = True
    return sections


def build_report(sections: list[StampedSection], unstamped: list[dict[str, object]]) -> dict[str, object]:
    green_drifted = [asdict(s) for s in sections if s.status == "green" and s.drifted]
    yellow_or_red = [asdict(s) for s in sections if s.status in {"yellow", "red"}]
    missing_paths = [asdict(s) for s in sections if s.missing_paths]
    return {
        "section_count": len(sections) + len(unstamped),
        "stamped_count": len(sections),
        "unstamped_count": len(unstamped),
        "green_drifted_count": len(green_drifted),
        "yellow_or_red_count": len(yellow_or_red),
        "missing_paths_count": len(missing_paths),
        "green_drifted": green_drifted,
        "yellow_or_red": yellow_or_red,
        "missing_paths": missing_paths,
        "unstamped": unstamped[:50],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect drift in stamped bible sections.")
    parser.add_argument("--bible", default=str(DEFAULT_BIBLE), help="Path to bible markdown.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any green section has drifted (default exits 0 advisory).",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    bible_path = Path(args.bible).expanduser()
    if not bible_path.is_absolute():
        bible_path = (ROOT / bible_path).resolve()
    sections, unstamped = parse_bible(bible_path)
    if not bible_path.exists():
        payload = {
            "ok": False,
            "error": f"bible not found: {bible_path}",
            "section_count": 0,
        }
        print(json.dumps(payload, sort_keys=True) if args.json else f"Bible drift: FAIL\n- {payload['error']}")
        return 1
    sections = evaluate_drift(ROOT, sections)
    report = build_report(sections, unstamped)
    report["ok"] = report["green_drifted_count"] == 0
    report["bible_path"] = str(bible_path)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"Bible drift: {'PASS' if report['ok'] else 'WARN'}")
        print(
            f"- sections={report['section_count']} stamped={report['stamped_count']} unstamped={report['unstamped_count']}"
        )
        print(
            f"- green_drifted={report['green_drifted_count']} yellow_or_red={report['yellow_or_red_count']} missing_paths={report['missing_paths_count']}"
        )
        for section in report["green_drifted"][:10]:
            print(f"  DRIFTED: section L{section['line_no']} `{section['title']}` (covers={section['covers']})")
        for section in report["missing_paths"][:10]:
            print(f"  MISSING: section L{section['line_no']} `{section['title']}` (missing={section['missing_paths']})")
    if args.strict and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
