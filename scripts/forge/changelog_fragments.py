"""Per-agent changelog fragments, compiled into CHANGELOG.md at release time.

Two agents writing one CHANGELOG.md took turns parking each other's words and
once swept the other's entries into a commit by accident. A fragment under
``changelog.d/<agent>-<slug>.md`` belongs to one agent: nobody edits anybody
else's, every commit carries its own fragment, and the release step folds all
of them into the version section, grouped by ``### Added`` / ``### Changed``
/ ``### Fixed`` / ``### Removed`` / ``### Security`` in that order, fragments
in filename order within each group.

Fragment shape (one or more sections, bullets in the changelog's own style):

    ### Changed

    - **What changed, as a sentence.** Why, in one or two more.

Usage:
    python scripts/forge/changelog_fragments.py check [paths...]
    python scripts/forge/changelog_fragments.py compile --version 0.19.40 [--date YYYY-MM-DD]
    python scripts/forge/changelog_fragments.py list
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRAGMENT_DIR = ROOT / "changelog.d"
CHANGELOG = ROOT / "CHANGELOG.md"
SECTIONS = ("Added", "Changed", "Fixed", "Removed", "Security")
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+\.md$")
_SECTION = re.compile(r"^### (Added|Changed|Fixed|Removed|Security)\s*$")
_BULLET = re.compile(r"^- \S")
_VERSION_HEADER = re.compile(r"^## \[(?P<version>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?\s*$")


@dataclass
class CompileResult:
    folded: int
    version: str
    problems: list[str] = field(default_factory=list)


def check_fragment(path: Path) -> list[str]:
    """Problems with one fragment; an empty list means it is well formed."""
    problems: list[str] = []
    if not _NAME.match(path.name):
        problems.append(f"{path.name}: name must be <agent>-<slug>.md, lowercase, hyphenated")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return problems + [f"{path.name}: unreadable: {exc}"]
    sections = parse_fragment(text)
    if not sections:
        problems.append(f"{path.name}: needs a section header, one of " + ", ".join(f"### {s}" for s in SECTIONS))
        if not any(_BULLET.match(line) for line in text.splitlines()):
            problems.append(f"{path.name}: has no bullet (a line starting with '- ')")
    for name, bullets in sections.items():
        if not bullets:
            problems.append(f"{path.name}: section {name} has no bullet (a line starting with '- ')")
    return problems


def parse_fragment(text: str) -> dict[str, list[str]]:
    """Section name -> bullets, each bullet with its continuation lines."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        head = _SECTION.match(line)
        if head:
            current = head.group(1)
            sections.setdefault(current, [])
            continue
        if current is None or not line.strip():
            continue
        if _BULLET.match(line):
            sections[current].append(line.rstrip())
        elif sections[current] and line.startswith("  "):
            sections[current][-1] += "\n" + line.rstrip()
    return sections


def list_fragments(fragment_dir: Path = FRAGMENT_DIR) -> list[Path]:
    if not fragment_dir.is_dir():
        return []
    return sorted(p for p in fragment_dir.iterdir() if p.suffix == ".md" and p.is_file() and p.name != "README.md")


def compile_fragments(
    changelog: Path = CHANGELOG,
    fragment_dir: Path = FRAGMENT_DIR,
    *,
    version: str,
    date: str | None = None,
) -> CompileResult:
    """Fold every fragment into ``## [version]``; refuse to touch anything if one is malformed."""
    fragments = list_fragments(fragment_dir)
    problems = [p for frag in fragments for p in check_fragment(frag)]
    if problems:
        return CompileResult(0, version, problems)
    if not fragments:
        return CompileResult(0, version)
    grouped: dict[str, list[str]] = {name: [] for name in SECTIONS}
    for frag in fragments:
        for name, bullets in parse_fragment(frag.read_text(encoding="utf-8")).items():
            grouped[name].extend(bullets)
    date = date or _dt.date.today().isoformat()
    text = _merge_into_changelog(changelog.read_text(encoding="utf-8"), version, date, grouped)
    changelog.write_text(text, encoding="utf-8", newline="\n")
    for frag in fragments:
        frag.unlink()
    return CompileResult(len(fragments), version)


def _version_index(lines: list[str], version: str) -> int | None:
    for i, line in enumerate(lines):
        m = _VERSION_HEADER.match(line)
        if m and m.group("version") == version:
            return i
    return None


def _merge_into_changelog(text: str, version: str, date: str, grouped: dict[str, list[str]]) -> str:
    lines = text.split("\n")
    header_idx = _version_index(lines, version)
    if header_idx is None:
        unreleased = next((i for i, line in enumerate(lines) if line.strip() == "## [Unreleased]"), None)
        insert_at = (unreleased + 2) if unreleased is not None else 0
        block = [f"## [{version}] - {date}", ""]
        for name in SECTIONS:
            if grouped[name]:
                block += [f"### {name}", ""] + _spaced(grouped[name]) + [""]
        lines[insert_at:insert_at] = block
        return "\n".join(lines)
    end_idx = next((i for i in range(header_idx + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = lines[header_idx + 1 : end_idx]
    for name in SECTIONS:
        if not grouped[name]:
            continue
        sub_idx = next((i for i, line in enumerate(section) if line.strip() == f"### {name}"), None)
        if sub_idx is None:
            while section and not section[-1].strip():
                section.pop()
            section += ["", f"### {name}", ""] + _spaced(grouped[name]) + [""]
            continue
        sub_end = next((i for i in range(sub_idx + 1, len(section)) if section[i].startswith("### ")), len(section))
        while sub_end > sub_idx + 1 and not section[sub_end - 1].strip():
            sub_end -= 1
        section[sub_end:sub_end] = [""] + _spaced(grouped[name])
    lines[header_idx + 1 : end_idx] = section
    return "\n".join(lines)


def _spaced(bullets: list[str]) -> list[str]:
    out: list[str] = []
    for i, bullet in enumerate(bullets):
        if i:
            out.append("")
        out.extend(bullet.split("\n"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-agent changelog fragments.")
    sub = parser.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check", help="Validate fragments (default: every fragment in changelog.d).")
    chk.add_argument("paths", nargs="*")
    comp = sub.add_parser("compile", help="Fold every fragment into the version section and delete them.")
    comp.add_argument("--version", required=True)
    comp.add_argument("--date", default=None)
    sub.add_parser("list", help="List fragments.")
    args = parser.parse_args(argv)
    if args.command == "list":
        for frag in list_fragments():
            print(frag.relative_to(ROOT).as_posix())
        return 0
    if args.command == "check":
        paths = [Path(p) for p in args.paths] or list_fragments()
        problems = [p for path in paths for p in check_fragment(path)]
        for problem in problems:
            print(f"- {problem}")
        print(f"changelog fragments: {'FAIL' if problems else 'PASS'} ({len(paths)} checked)")
        return 1 if problems else 0
    result = compile_fragments(version=args.version, date=args.date)
    for problem in result.problems:
        print(f"- {problem}")
    print(f"changelog fragments: {'FAIL' if result.problems else 'PASS'} folded {result.folded} into [{result.version}]")
    return 1 if result.problems else 0


if __name__ == "__main__":
    sys.exit(main())
