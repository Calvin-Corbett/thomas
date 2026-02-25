"""Record a signed module-audit entry and optionally update CHANGELOG."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, List, Set

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from thomas.observability.module_audit import (
    MAJOR_MODULES,
    build_file_hashes,
    default_registry_path,
    module_for_path,
    normalize_path,
    record_audit,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _insert_or_append(lines: List[str], idx: int, payload: List[str]) -> List[str]:
    return lines[:idx] + payload + lines[idx:]


def append_unreleased_audit_line(changelog_path: Path, line: str) -> bool:
    if not changelog_path.exists():
        return False
    text = changelog_path.read_text(encoding="utf-8")
    if line in text:
        return False

    lines = text.splitlines()
    unreleased_idx = next((i for i, raw in enumerate(lines) if raw.strip() == "## [Unreleased]"), None)
    if unreleased_idx is None:
        return False

    next_section_idx = next(
        (i for i in range(unreleased_idx + 1, len(lines)) if lines[i].startswith("## [")),
        len(lines),
    )
    audits_idx = next(
        (i for i in range(unreleased_idx + 1, next_section_idx) if lines[i].strip() == "### Audits"),
        None,
    )

    if audits_idx is None:
        insertion = ["", "### Audits", "", line]
        lines = _insert_or_append(lines, next_section_idx, insertion)
    else:
        insert_at = audits_idx + 1
        # Skip existing blank lines + bullets.
        while insert_at < next_section_idx and (
            lines[insert_at].strip() == "" or lines[insert_at].lstrip().startswith("- ")
        ):
            insert_at += 1
        lines = _insert_or_append(lines, insert_at, [line])

    changelog_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return True


def _modules_from_files(paths: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    for raw in paths:
        module = module_for_path(raw)
        if module:
            out.add(module)
    return out


def run(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record module-level audit entries.")
    parser.add_argument("--module", action="append", default=[], help=f"Module name ({', '.join(MAJOR_MODULES)})")
    parser.add_argument("--file", action="append", default=[], help="Changed file path (auto-detect module)")
    parser.add_argument("--auditor", default="doctor-bot", help="Auditor identity (default: doctor-bot)")
    parser.add_argument("--status", default="pass", choices=["pass", "warn", "fail", "pending_review"])
    parser.add_argument("--summary", default="", help="Short audit summary")
    parser.add_argument(
        "--issue",
        action="append",
        default=[],
        help="Issue/finding captured in the audit entry (repeatable).",
    )
    parser.add_argument("--run-id", default="", help="Optional run identifier")
    parser.add_argument("--registry", default="", help="Registry path (default: docs/ops/module_audit_log.json)")
    parser.add_argument("--changelog", default="CHANGELOG.md", help="Changelog path relative to repo root")
    parser.add_argument("--no-changelog", action="store_true", help="Do not append a changelog audit note")
    parser.add_argument("--signing-key", default="", help="Optional explicit signing key (overrides env)")
    args = parser.parse_args(argv)

    root = _repo_root()
    registry_path = Path(args.registry) if args.registry else default_registry_path(root)
    if not registry_path.is_absolute():
        registry_path = (root / registry_path).resolve()

    changelog_path = (root / args.changelog).resolve()
    signing_key = str(args.signing_key or os.environ.get("THOMAS_AUDIT_SIGNING_KEY") or "").strip() or None

    explicit_modules = {str(m or "").strip() for m in args.module if str(m or "").strip()}
    file_modules = _modules_from_files(normalize_path(p) for p in args.file)
    modules = sorted(explicit_modules | file_modules)
    if not modules:
        print("No modules provided. Use --module or --file.")
        return 2

    for module in modules:
        module_files = sorted(
            {
                normalize_path(p)
                for p in args.file
                if module_for_path(p) == module and normalize_path(p)
            }
        )
        file_hashes = build_file_hashes(root, module_files)
        entry = record_audit(
            registry_path=registry_path,
            module=module,
            auditor=args.auditor,
            status=args.status,
            summary=args.summary,
            run_id=args.run_id,
            files_touched=module_files,
            file_hashes=file_hashes,
            issues=args.issue,
            signing_key=signing_key,
        )
        sig_short = str(entry.get("signature", ""))[:12]
        print(
            f"Recorded module audit: module={module} status={entry['status']} "
            f"auditor={entry['auditor']} sig={sig_short}"
        )
        if not args.no_changelog:
            line = (
                f"- Module `thomas/{module}` audited by `{entry['auditor']}` on "
                f"{entry['audited_at'][:10]} (status: {entry['status']}, sig: `{sig_short}`)."
            )
            if append_unreleased_audit_line(changelog_path, line):
                print(f"Updated changelog with audit line for module={module}")

    print(f"Registry written: {registry_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

