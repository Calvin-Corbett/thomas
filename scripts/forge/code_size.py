"""Real code lines: the softer size line that sits under the physical-line cap.

The monolith guard's cap counts every physical line, so a file can sit at 798 lines by trimming blank lines, and a
docstring edit on a file already over the cap is refused. This module counts something nearer to complexity: the lines
of a Python file that hold code. It is a warning line (:data:`SOFT_REAL_CODE_LINES`), not a second cap. A file over it
is recorded in ``docs/monolith_soft_recorded.txt`` (one ``path real_lines`` per line), the record can only go down, and
the fix for a file over it is to split it by responsibility. The test that holds the record is
``tests/test_no_file_crosses_the_soft_code_line.py``.

What counts as a real code line (``.py`` files only):

* A physical line counts when at least one token on it is code: a name, number, operator, string or bracket.
* A blank line does not count.
* A comment-only line does not count. A line with code and a trailing comment counts.
* A docstring does not count: the string that opens a module, class or function body, on every line it spans.
* A data table does not count: a module-level or class-level assignment of a literal (or of names and attributes
  arranged in literal dicts, lists, tuples and sets) that spans more than one line, on every line it spans. A table
  written on one line counts as one line, since it is one line of code.
* Any other string (a multi-line SQL text, an f-string template inside a function) counts on every line it spans.
* A file that does not parse falls back to: non-blank lines that do not start with ``#``.

This file launches no process. The caller says which files to measure.
"""

from __future__ import annotations

import ast
import io
import json
import sys
import tokenize
from collections.abc import Iterable
from pathlib import Path

#: Real code lines above which a file is recorded and asked to split. A warning line, under the physical-line cap.
SOFT_REAL_CODE_LINES = 700
RECORD_NAME = "docs/monolith_soft_recorded.txt"
BASELINE_NAME = "docs/monolith_guard_baseline.json"

_NOT_CODE = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
}


def _is_table(node: ast.AST) -> bool:
    """A literal dict, list, tuple or set, or a string/number, whose parts are literals, names or attributes."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Name, ast.Attribute)):
        return True
    if isinstance(node, ast.UnaryOp):
        return _is_table(node.operand)
    if isinstance(node, ast.Dict):
        return all(k is not None and _is_table(k) and _is_table(v) for k, v in zip(node.keys, node.values, strict=True))
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_table(e) for e in node.elts)
    return False


def _docstring_and_table_spans(tree: ast.Module) -> list[tuple[int, int]]:
    """Line spans that do not count: docstrings anywhere, and multi-line data tables at module and class level."""
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                spans.append((first.lineno, first.end_lineno or first.lineno))
    scopes: list[list[ast.stmt]] = [tree.body]
    scopes.extend(n.body for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    for body in scopes:
        for stmt in body:
            value = stmt.value if isinstance(stmt, (ast.Assign, ast.AnnAssign)) else None
            end = stmt.end_lineno or stmt.lineno
            if value is not None and end > stmt.lineno and _is_table(value):
                spans.append((stmt.lineno, end))
    return spans


def _fallback(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#"))


def real_code_lines(text: str) -> int:
    """How many lines of this Python source hold real code, by the rules in the module docstring."""
    try:
        tree = ast.parse(text)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (SyntaxError, ValueError, tokenize.TokenError):
        return _fallback(text)
    skipped: set[int] = set()
    for start, end in _docstring_and_table_spans(tree):
        skipped.update(range(start, end + 1))
    code: set[int] = set()
    for tok in tokens:
        if tok.type in _NOT_CODE:
            continue
        code.update(range(tok.start[0], tok.end[0] + 1))
    return len(code - skipped)


def real_code_lines_of(path: Path) -> int:
    return real_code_lines(path.read_text(encoding="utf-8", errors="replace"))


def physical_lines(path: Path) -> int:
    """The monolith guard's own count: every line of the file."""
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        return sum(1 for _ in fh)


def hard_cap(root: Path) -> int:
    """The physical-line cap on an unbaselined file, read from the baseline the guard reads. Zero if there is none."""
    try:
        raw = json.loads((root / BASELINE_NAME).read_text(encoding="utf-8"))
        return max(0, int(raw["waiver_policy"]["unbaselined_soft_limit_lines"]))
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def measure(root: Path, rel_paths: Iterable[str], *, cap: int | None = None) -> dict[str, int]:
    """Real code lines of each ``.py`` file over :data:`SOFT_REAL_CODE_LINES` that is not over the physical-line cap.

    A file already over the cap is the cap's business, so it is not listed here. Anything that is not a file is skipped.
    """
    limit = hard_cap(root) if cap is None else cap
    over: dict[str, int] = {}
    for rel in rel_paths:
        path = root / rel
        if not rel.endswith(".py") or not path.is_file():
            continue
        real = real_code_lines_of(path)
        if real > SOFT_REAL_CODE_LINES and not (limit and physical_lines(path) > limit):
            over[rel] = real
    return over


def read_record(path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            name, _, count = line.rpartition(" ")
            out[name] = int(count)
    return out


def format_record(record: dict[str, int]) -> str:
    return "".join(f"{name} {count}\n" for name, count in sorted(record.items()))


def judge(measured: dict[str, int], recorded: dict[str, int], cap: int) -> list[str]:
    """What is wrong between the measurement and the record. Empty means the record is exact."""
    problems: list[str] = []
    for rel, real in sorted(measured.items()):
        if rel not in recorded:
            problems.append(
                f"{rel} has {real} real code lines, over the soft line of {SOFT_REAL_CODE_LINES}, and is not recorded. "
                f"The hard cap is {cap} lines. Split it by responsibility into modules that each hold one job; "
                "do not raise a number or add it to the record."
            )
        elif real > recorded[rel]:
            problems.append(
                f"{rel} grew from {recorded[rel]} to {real} real code lines. Split it by responsibility; "
                "do not raise the record."
            )
    for rel, was in sorted(recorded.items()):
        if rel in measured and measured[rel] < was:
            problems.append(
                f"{rel} shrank from {was} to {measured[rel]} real code lines. Lower its line in "
                f"{RECORD_NAME} to {measured[rel]} so the room it gave up is not left for growth."
            )
        elif rel not in measured:
            problems.append(
                f"{rel} is recorded at {was} real code lines but is no longer over {SOFT_REAL_CODE_LINES}, "
                f"missing, or over the hard cap of {cap}. Drop its line from {RECORD_NAME}."
            )
    return problems


def warning_lines(root: Path, rel_paths: Iterable[str]) -> list[str]:
    """The warning the monolith guard prints for the files a commit touches that are over the soft line. Empty if none."""
    over = measure(root, rel_paths)
    if not over:
        return []
    recorded = read_record(root / RECORD_NAME)
    lines = [
        f"Monolith soft line (warning only): {len(over)} touched file(s) over {SOFT_REAL_CODE_LINES} real code lines "
        f"(hard cap {hard_cap(root)} lines). Split each by responsibility; nothing here is raised."
    ]
    for rel, real in sorted(over.items()):
        note = (
            "recorded" if rel in recorded else "NOT recorded, so the soft-line test in tests/ fails until it is split"
        )
        lines.append(f"- {rel}: {real} real code lines ({note})")
    return lines


def lowered(measured: dict[str, int], recorded: dict[str, int]) -> dict[str, int]:
    """The record after a split: entries that are gone dropped, entries that shrank lowered. Nothing added or raised."""
    return {rel: min(was, measured[rel]) for rel, was in recorded.items() if rel in measured}


def main(argv: list[str] | None = None) -> int:
    """Read tracked file names on stdin (``git ls-files "*.py" | python -m scripts.forge.code_size``).

    No flag: print the files over the soft line. ``--init``: write the record from measurement, only when there is
    none yet. ``--lower``: rewrite the record with what a split removed, and refuse if the measurement has an
    entry the record does not.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[2]
    cap = hard_cap(root)
    measured = measure(root, (line.strip() for line in sys.stdin), cap=cap)
    record_path = root / RECORD_NAME
    if "--init" in args:
        if record_path.exists():
            print(f"{RECORD_NAME} exists; use --lower.")
            return 1
        record_path.write_text(format_record(measured), encoding="utf-8", newline="\n")
        print(f"Wrote {len(measured)} files to {RECORD_NAME}.")
        return 0
    if "--lower" in args:
        recorded = read_record(record_path)
        new = sorted(set(measured) - set(recorded))
        if new:
            print("Not recorded, and a record only goes down. Split these by responsibility:\n" + "\n".join(new))
            return 1
        record_path.write_text(format_record(lowered(measured, recorded)), encoding="utf-8", newline="\n")
        print(f"Record lowered to {len(lowered(measured, recorded))} files.")
        return 0
    for rel, real in sorted(measured.items(), key=lambda item: -item[1]):
        print(f"{rel} {real}")
    print(f"{len(measured)} files over {SOFT_REAL_CODE_LINES} real code lines (hard cap {cap} lines).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
