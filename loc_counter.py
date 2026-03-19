#!/usr/bin/env python3
"""
loc_counter.py  —  Lines-of-Code counter
Usage:
    python loc_counter.py                     # count current directory
    python loc_counter.py /path/to/repo       # count a specific path
    python loc_counter.py . --top 20          # show top 20 files
    python loc_counter.py . --ext py js ts    # only these extensions
    python loc_counter.py . --no-blanks       # already the default, explicit
    python loc_counter.py . --include-blanks  # count blank lines too
    python loc_counter.py . --json            # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Language definitions  (extension → display name, comment prefixes)
# ---------------------------------------------------------------------------
LANGUAGES: dict[str, tuple[str, list[str]]] = {
    ".py": ("Python", ["#"]),
    ".js": ("JavaScript", ["//"]),
    ".ts": ("TypeScript", ["//"]),
    ".jsx": ("JSX", ["//"]),
    ".tsx": ("TSX", ["//"]),
    ".html": ("HTML", ["<!--"]),
    ".css": ("CSS", ["/*"]),
    ".scss": ("SCSS", ["//"]),
    ".json": ("JSON", []),
    ".toml": ("TOML", ["#"]),
    ".yaml": ("YAML", ["#"]),
    ".yml": ("YAML", ["#"]),
    ".sh": ("Shell", ["#"]),
    ".ps1": ("PowerShell", ["#"]),
    ".bat": ("Batch", ["REM", "::"]),
    ".md": ("Markdown", []),
    ".txt": ("Text", []),
    ".rst": ("reStructured", []),
    ".go": ("Go", ["//"]),
    ".rs": ("Rust", ["//"]),
    ".java": ("Java", ["//"]),
    ".kt": ("Kotlin", ["//"]),
    ".c": ("C", ["//"]),
    ".cpp": ("C++", ["//"]),
    ".h": ("C Header", ["//"]),
    ".cs": ("C#", ["//"]),
    ".rb": ("Ruby", ["#"]),
    ".php": ("PHP", ["//"]),
    ".sql": ("SQL", ["--"]),
    ".lua": ("Lua", ["--"]),
    ".r": ("R", ["#"]),
    ".swift": ("Swift", ["//"]),
}

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "coverage",
    ".tox",
    "eggs",
    "*.egg-info",
    ".idea",
    ".vscode",
    # Doppelganger Protocol isolated venvs — not project code
    "runtime",
    "doppelganger",
    "site-packages",
}


# ---------------------------------------------------------------------------
# Core counting
# ---------------------------------------------------------------------------


def count_file(path: Path, include_blanks: bool) -> tuple[int, int, int]:
    """Returns (total_lines, code_lines, blank_lines)."""
    ext = path.suffix.lower()
    _, comment_prefixes = LANGUAGES.get(ext, ("", []))

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (PermissionError, OSError):
        return 0, 0, 0

    total = 0
    code = 0
    blank = 0

    for raw_line in text.splitlines():
        total += 1
        line = raw_line.strip()
        if not line:
            blank += 1
        elif any(line.startswith(p) for p in comment_prefixes):
            pass  # comment line — don't count as code
        else:
            code += 1

    return total, code, blank


def walk(
    root: Path,
    extensions: list[str] | None,
    include_blanks: bool,
) -> list[dict]:
    """Walk root and return per-file stats."""
    results = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()

            if extensions and ext not in extensions:
                continue
            if ext not in LANGUAGES and not extensions:
                continue

            total, code, blank = count_file(fpath, include_blanks)
            if total == 0:
                continue

            lang_name, _ = LANGUAGES.get(ext, (ext or "Unknown", []))
            results.append(
                {
                    "path": str(fpath.relative_to(root)),
                    "language": lang_name,
                    "ext": ext,
                    "total": total,
                    "code": code,
                    "blank": blank,
                    "comment": total - code - blank,
                }
            )

    return results


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _bar(value: int, max_value: int, width: int = 20) -> str:
    if max_value == 0:
        return " " * width
    filled = int(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


def _sep(widths: list[int], char: str = "─") -> str:
    return "┼".join(char * (w + 2) for w in widths)


def print_results(
    results: list[dict],
    root: Path,
    top_n: int,
    include_blanks: bool,
    show_json: bool,
) -> None:
    if not results:
        print("No source files found.")
        return

    if show_json:
        print(json.dumps(results, indent=2))
        return

    # ── By language ──────────────────────────────────────────────────────
    by_lang: dict[str, dict] = defaultdict(lambda: {"files": 0, "total": 0, "code": 0, "blank": 0, "comment": 0})
    for r in results:
        b = by_lang[r["language"]]
        b["files"] += 1
        b["total"] += r["total"]
        b["code"] += r["code"]
        b["blank"] += r["blank"]
        b["comment"] += r["comment"]

    lang_rows = sorted(by_lang.items(), key=lambda x: x[1]["code"], reverse=True)
    total_code = sum(v["code"] for v in by_lang.values())
    total_lines = sum(v["total"] for v in by_lang.values())
    total_files = sum(v["files"] for v in by_lang.values())
    max_code = max(v["code"] for v in by_lang.values()) if lang_rows else 1

    BAR_W = 22
    col_widths = [16, 6, 8, 8, 8, 8, BAR_W]
    headers = ["Language", "Files", "Total", "Code", "Blank", "Comment", "Distribution"]

    print()
    print(f"  📁  {root.resolve()}")
    print()

    def row_fmt(cols: list[str]) -> str:
        parts = []
        for i, (w, c) in enumerate(zip(col_widths, cols)):
            if i == 0 or i == len(col_widths) - 1:
                parts.append(f" {c:<{w}} ")
            else:
                parts.append(f" {c:>{w}} ")
        return "│".join(parts)

    sep_line = "┼".join("─" * (w + 2) for w in col_widths)

    print("┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐")
    print("│" + row_fmt([h for h in headers]) + "│")
    print("├" + sep_line + "┤")

    for lang, stats in lang_rows:
        bar = _bar(stats["code"], max_code, BAR_W)
        pct = stats["code"] / total_code * 100 if total_code else 0
        bar_label = f"{bar} {pct:4.1f}%"
        print(
            "│"
            + row_fmt(
                [
                    lang,
                    str(stats["files"]),
                    f"{stats['total']:,}",
                    f"{stats['code']:,}",
                    f"{stats['blank']:,}",
                    f"{stats['comment']:,}",
                    bar_label[:BAR_W],
                ]
            )
            + "│"
        )

    print("├" + sep_line + "┤")
    print(
        "│"
        + row_fmt(
            [
                "TOTAL",
                str(total_files),
                f"{total_lines:,}",
                f"{total_code:,}",
                str(sum(v["blank"] for v in by_lang.values())),
                str(sum(v["comment"] for v in by_lang.values())),
                "",
            ]
        )
        + "│"
    )
    print("└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘")

    # ── Top N files ───────────────────────────────────────────────────────
    sorted_files = sorted(results, key=lambda x: x["code"], reverse=True)
    top = sorted_files[:top_n]
    if not top:
        return

    max_file_code = top[0]["code"] if top else 1
    path_w = min(60, max(len(r["path"]) for r in top) + 2)

    print()
    print(f"  Top {len(top)} files by code lines:")
    print()

    file_col_widths = [path_w, 14, 8, 8, 8]
    file_headers = ["File", "Language", "Code", "Total", "Blank"]
    file_sep = "┼".join("─" * (w + 2) for w in file_col_widths)

    def file_row_fmt(cols: list[str]) -> str:
        parts = []
        for i, (w, c) in enumerate(zip(file_col_widths, cols)):
            if i == 0:
                parts.append(f" {c:<{w}} ")
            else:
                parts.append(f" {c:>{w}} ")
        return "│".join(parts)

    print("┌" + "┬".join("─" * (w + 2) for w in file_col_widths) + "┐")
    print("│" + file_row_fmt(file_headers) + "│")
    print("├" + file_sep + "┤")

    for r in top:
        bar = _bar(r["code"], max_file_code, 6)
        path_display = r["path"]
        if len(path_display) > path_w:
            path_display = "…" + path_display[-(path_w - 1) :]
        print(
            "│"
            + file_row_fmt(
                [
                    path_display,
                    r["language"],
                    f"{r['code']:,}",
                    f"{r['total']:,}",
                    f"{r['blank']:,}",
                ]
            )
            + "│"
        )

    print("└" + "┴".join("─" * (w + 2) for w in file_col_widths) + "┘")
    print()
    print(f"  Total code lines: {total_code:,}  |  Total files: {total_files:,}  |  Total lines: {total_lines:,}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Count lines of code in a directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to count (default: current directory)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        metavar="N",
        help="Show top N files by code lines (default: 15)",
    )
    parser.add_argument(
        "--ext",
        nargs="+",
        metavar="EXT",
        help="Only count these extensions, e.g. --ext py js ts",
    )
    parser.add_argument(
        "--include-blanks",
        action="store_true",
        help="Include blank lines in the code count",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON (per-file stats)",
    )
    parser.add_argument(
        "--list-langs",
        action="store_true",
        help="Print all supported languages and exit",
    )
    args = parser.parse_args()

    if args.list_langs:
        print("\nSupported languages:")
        for ext, (name, _) in sorted(LANGUAGES.items(), key=lambda x: x[1][0]):
            print(f"  {ext:<10} {name}")
        print()
        return

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"Error: path not found: {root}", file=sys.stderr)
        sys.exit(1)
    if not root.is_dir():
        # Single file mode
        ext = root.suffix.lower()
        lang_name, _ = LANGUAGES.get(ext, (ext or "Unknown", []))
        total, code, blank = count_file(root, args.include_blanks)
        print(f"\n{root.name}  ({lang_name})")
        print(f"  Total lines : {total:,}")
        print(f"  Code lines  : {code:,}")
        print(f"  Blank lines : {blank:,}")
        print(f"  Comments    : {total - code - blank:,}")
        print()
        return

    extensions = None
    if args.ext:
        extensions = [e if e.startswith(".") else f".{e}" for e in args.ext]

    if not args.json:
        print("\n  Counting…", end="\r")

    results = walk(root, extensions, args.include_blanks)

    print_results(
        results,
        root=root,
        top_n=args.top,
        include_blanks=args.include_blanks,
        show_json=args.json,
    )


if __name__ == "__main__":
    main()
