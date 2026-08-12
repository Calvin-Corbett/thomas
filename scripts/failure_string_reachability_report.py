"""Failure-string reachability report (REPORT-ONLY -- never a gate).

Scans thomas/ for hand-written user-facing failure/fallback sentences and
checks whether any test under tests/ references each sentence. The point is
to surface the recurring "lie structure": a carefully worded fallback
sentence sitting in a branch that no test ever reaches or asserts.

Hard constraints (owner-mandated, do not change):
  * This script ALWAYS exits 0 -- even on internal errors.
  * It must NEVER be wired into pre-commit or CI as a blocker.
  * It reports; it never rejects, gates, or fails anything.

Output: a readable report on stdout and reports/failure_string_reachability.md.

Heuristics are intentionally loose. False positives are tolerable; the report
is for a human to read, not for a machine to enforce.
"""

from __future__ import annotations

import ast
import bisect
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PY_SCAN_ROOT = REPO_ROOT / "thomas"
JS_SCAN_ROOT = REPO_ROOT / "thomas" / "server" / "web" / "js"
TESTS_ROOT = REPO_ROOT / "tests"
REPORT_PATH = REPO_ROOT / "reports" / "failure_string_reachability.md"

# Sentence shape: >= 4 words, starts with an uppercase letter, ends in . ! or ?
MIN_WORDS = 4
MAX_LEN = 240  # longer strings are prompts/docs, not user-facing fallbacks

# Dict keys whose string values are plausibly shown to a user (json_response
# error payloads, structured failure records, ...).
USER_FACING_DICT_KEYS = {
    "error",
    "message",
    "reason",
    "detail",
    "details",
    "hint",
    "fallback",
    "error_message",
    "failure",
    "status_text",
}

# Variable names (or suffixes) whose assignment looks like a fallback sentence.
USER_FACING_VAR_NAMES = {
    "reason",
    "message",
    "error",
    "detail",
    "details",
    "hint",
    "fallback",
    "summary",
    "error_message",
    "failure",
    "failure_reason",
    "status_message",
    "user_message",
}
USER_FACING_VAR_SUFFIXES = ("_reason", "_message", "_error", "_hint", "_fallback", "_detail", "_summary")

# Keyword-argument names that carry user-facing text.
USER_FACING_KWARGS = {
    "reason",
    "message",
    "error",
    "detail",
    "hint",
    "fallback",
    "description",
    "error_message",
    "text",
}

# Call names (last attribute segment) whose positional string args face users
# or the log-and-return path.
USER_FACING_CALL_NAMES = {
    "json_response",
    "warning",
    "error",
    "exception",
    "critical",
    "fail",
    "abort",
}

# JS error helpers: the fallback sentence is a non-first argument.
JS_HELPER_NAMES = ("errorText", "recordError", "safely")
JS_HELPER_RE = re.compile(r"\b(?:" + "|".join(JS_HELPER_NAMES) + r")\s*\(")

_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Collapse whitespace and drop backslashes so escaped test literals match."""
    return _WS_RE.sub(" ", text.replace("\\", "")).strip()


def looks_like_sentence(raw: str) -> str | None:
    """Return the trimmed sentence if `raw` matches the target shape, else None."""
    text = raw.strip()
    if not text or len(text) > MAX_LEN or "\n" in text:
        return None
    if text[-1] not in ".!?":
        return None
    first = text[0]
    if not (first.isalpha() and first.isupper()):
        return None
    if len(text.split()) < MIN_WORDS:
        return None
    return text


@dataclass
class Occurrence:
    path: Path  # relative to repo root
    line: int
    context: str


@dataclass
class Sentence:
    text: str
    occurrences: list[Occurrence] = field(default_factory=list)
    tested: bool = False
    match_note: str = ""  # which test file / match kind


# ---------------------------------------------------------------------------
# Python scanning
# ---------------------------------------------------------------------------


def _last_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_user_facing_target(target: ast.expr) -> bool:
    name = _last_name(target).lower()
    return bool(name) and (name in USER_FACING_VAR_NAMES or name.endswith(USER_FACING_VAR_SUFFIXES))


def _dict_key_for_value(parent: ast.Dict, child: ast.expr) -> str | None:
    for key, value in zip(parent.keys, parent.values):
        if value is child and isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value
    return None


def classify_context(ancestors: list[ast.AST], node: ast.AST) -> str | None:
    """Walk outward from the string node; return a context label or None.

    Transparent wrappers (BoolOp `or` fallbacks, ternaries, f-strings, string
    concatenation) are skipped so `x or "Sentence."` still classifies by what
    surrounds it.
    """
    child: ast.AST = node
    for parent in reversed(ancestors):
        if isinstance(parent, ast.Expr):
            return None  # docstring / bare string statement
        if isinstance(parent, ast.Raise):
            return "raise"
        if isinstance(parent, ast.Dict):
            key = _dict_key_for_value(parent, child)  # type: ignore[arg-type]
            if key is not None:
                return f'dict["{key}"]' if key.lower() in USER_FACING_DICT_KEYS else None
        if isinstance(parent, ast.Assign) and any(_is_user_facing_target(t) for t in parent.targets):
            return f"{_last_name(parent.targets[0])} ="
        if isinstance(parent, ast.AnnAssign) and _is_user_facing_target(parent.target):
            return f"{_last_name(parent.target)} ="
        if isinstance(parent, ast.keyword):
            if parent.arg and parent.arg.lower() in USER_FACING_KWARGS:
                return f"{parent.arg}=..."
            return None
        if isinstance(parent, ast.Call) and child is not parent.func:
            name = _last_name(parent.func)
            if name in USER_FACING_CALL_NAMES:
                return f"{name}(...)"
            if name.endswith(("Error", "Exception")):
                return f"{name}(...)"
            # Keep climbing: the call may itself sit inside a raise/dict/etc.
        if isinstance(parent, ast.Return):
            return "return"
        if isinstance(parent, ast.stmt):
            return None  # reached statement level with no user-facing shape
        child = parent
    return None


def scan_python_file(path: Path, sentences: dict[str, Sentence]) -> None:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, ValueError, OSError):
        return
    rel = path.relative_to(REPO_ROOT)

    def visit(node: ast.AST, ancestors: list[ast.AST]) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            sentence = looks_like_sentence(node.value)
            if sentence:
                context = classify_context(ancestors, node)
                if context:
                    entry = sentences.setdefault(_normalize(sentence), Sentence(text=sentence))
                    entry.occurrences.append(Occurrence(rel, getattr(node, "lineno", 0), context))
            return
        ancestors.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child, ancestors)
        ancestors.pop()

    visit(tree, [])


# ---------------------------------------------------------------------------
# JS scanning
# ---------------------------------------------------------------------------


def _extract_js_fallback(source: str, open_paren: int) -> tuple[str, int] | None:
    """From an opening paren, return (string, offset) for the first quoted
    literal that is a non-first top-level argument of the call."""
    depth = 0
    seen_top_level_comma = False
    i = open_paren
    n = len(source)
    while i < n:
        ch = source[i]
        if ch in "\"'`":
            quote = ch
            start = i + 1
            i += 1
            buf: list[str] = []
            while i < n and source[i] != quote:
                if source[i] == "\\":
                    i += 1
                    if i < n:
                        buf.append(source[i])
                else:
                    buf.append(source[i])
                i += 1
            if depth == 1 and seen_top_level_comma:
                return "".join(buf), start
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth <= 0:
                return None
        elif ch == "," and depth == 1:
            seen_top_level_comma = True
        i += 1
    return None


def scan_js_file(path: Path, sentences: dict[str, Sentence]) -> None:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    rel = path.relative_to(REPO_ROOT)
    for match in JS_HELPER_RE.finditer(source):
        helper = source[match.start() : match.end() - 1].strip().rstrip("(").strip()
        extracted = _extract_js_fallback(source, match.end() - 1)
        if not extracted:
            continue
        text, offset = extracted
        sentence = looks_like_sentence(text)
        if not sentence:
            continue
        line = source.count("\n", 0, offset) + 1
        entry = sentences.setdefault(_normalize(sentence), Sentence(text=sentence))
        entry.occurrences.append(Occurrence(rel, line, f"{helper}(..., ...)"))


# ---------------------------------------------------------------------------
# Test corpus search
# ---------------------------------------------------------------------------


class TestCorpus:
    def __init__(self, root: Path) -> None:
        chunks: list[str] = []
        self.offsets: list[int] = []
        self.files: list[Path] = []
        pos = 0
        skip_dirs = {"__pycache__", ".pytest_cache", ".git"}
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if not path.is_file() or skip_dirs.intersection(path.parts):
                    continue
                try:
                    raw = path.read_bytes()
                except OSError:
                    continue
                if b"\x00" in raw[:4096]:
                    continue  # binary artifact (compiled, db, image, ...)
                text = raw.decode("utf-8", errors="ignore")
                normalized = _normalize(text)
                self.offsets.append(pos)
                self.files.append(path.relative_to(REPO_ROOT))
                chunks.append(normalized)
                pos += len(normalized) + 1
        self.blob = "\n".join(chunks)

    def _file_at(self, position: int) -> str:
        idx = bisect.bisect_right(self.offsets, position) - 1
        if 0 <= idx < len(self.files):
            return self.files[idx].as_posix()
        return "?"

    def find(self, needle: str) -> str | None:
        position = self.blob.find(needle)
        if position >= 0:
            return self._file_at(position)
        return None


def check_tested(sentence: Sentence, corpus: TestCorpus) -> None:
    normalized = _normalize(sentence.text)
    found = corpus.find(normalized)
    if found:
        sentence.tested = True
        sentence.match_note = f"exact match in {found}"
        return
    # Lenient pass for long sentences that tests may quote only partially:
    # try the leading and trailing 6-word spans.
    words = normalized.rstrip(".!?").split()
    if len(words) >= 8:
        for label, span in (("leading", words[:6]), ("trailing", words[-6:])):
            found = corpus.find(" ".join(span))
            if found:
                sentence.tested = True
                sentence.match_note = f"{label} 6-word span match in {found}"
                return
    sentence.tested = False


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def build_report(sentences: list[Sentence]) -> str:
    untested = [s for s in sentences if not s.tested]
    tested = [s for s in sentences if s.tested]
    total_occurrences = sum(len(s.occurrences) for s in sentences)

    lines: list[str] = []
    lines.append("# Failure-string reachability report")
    lines.append("")
    lines.append("REPORT-ONLY. This tool never gates, never rejects, and always exits 0.")
    lines.append("Do not wire it into pre-commit or CI as a blocker.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- User-facing failure/fallback sentences found: **{len(sentences)}** "
                 f"({total_occurrences} occurrences)")
    lines.append(f"- Referenced by no test under tests/: **{len(untested)}**")
    lines.append(f"- Referenced by at least one test: **{len(tested)}**")
    lines.append("")

    def emit_group(title: str, group: list[Sentence], show_match: bool) -> None:
        lines.append(f"## {title} ({len(group)})")
        lines.append("")
        by_file: dict[str, list[tuple[Occurrence, Sentence]]] = {}
        for sentence in group:
            for occurrence in sentence.occurrences:
                by_file.setdefault(occurrence.path.as_posix(), []).append((occurrence, sentence))
        for file_path in sorted(by_file):
            lines.append(f"### {file_path}")
            lines.append("")
            for occurrence, sentence in sorted(by_file[file_path], key=lambda item: item[0].line):
                lines.append(f"- `{file_path}:{occurrence.line}` [{occurrence.context}]")
                lines.append(f"  > {sentence.text}")
                if show_match and sentence.match_note:
                    lines.append(f"  - {sentence.match_note}")
            lines.append("")

    emit_group("Untested sentences", sorted(untested, key=lambda s: s.text), show_match=False)
    emit_group("Tested sentences", sorted(tested, key=lambda s: s.text), show_match=True)
    return "\n".join(lines)


def main() -> None:
    sentences_by_key: dict[str, Sentence] = {}

    for path in sorted(PY_SCAN_ROOT.rglob("*.py")):
        scan_python_file(path, sentences_by_key)
    for path in sorted(JS_SCAN_ROOT.rglob("*.js")):
        scan_js_file(path, sentences_by_key)

    corpus = TestCorpus(TESTS_ROOT)
    sentences = list(sentences_by_key.values())
    for sentence in sentences:
        check_tested(sentence, corpus)

    report = build_report(sentences)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n(report written to {REPORT_PATH.relative_to(REPO_ROOT).as_posix()})")


# The failures a filesystem walk, an ast parse, or report assembly can
# realistically produce. Named rather than broad so a bug in this tool still
# shows its face in full -- while the report itself keeps its one promise:
# it exits 0. KeyboardInterrupt and SystemExit deliberately pass through;
# a human cancelling the run is not the report failing.
_REPORT_ERRORS = (
    ArithmeticError,
    AttributeError,
    ImportError,
    LookupError,
    MemoryError,
    NameError,
    OSError,
    RecursionError,
    RuntimeError,
    SyntaxError,
    TypeError,
    UnicodeError,
    ValueError,
)

if __name__ == "__main__":
    try:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
        main()
    except _REPORT_ERRORS:  # report-only: never fail, even on internal errors
        traceback.print_exc()
    sys.exit(0)
