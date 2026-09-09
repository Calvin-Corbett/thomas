"""Change-scoped security scanning that feeds confirmed findings back into
generation (CAP-083).

The generation loop (Forge / Anvil evolve runtime) produces *changes* -- sets
of file edits.  Rather than scanning the whole repository, this module scans
**every generated change** for a starter set of security defects, using a
deterministic ``ast``-based analysis of each edited file's post-edit content:

- hardcoded secret / credential literals,
- ``eval`` / ``exec`` dynamic code execution,
- ``subprocess`` calls with ``shell=True``,
- unsafe deserialization via ``pickle.loads`` / ``cPickle.loads``,
- SQL built by string concatenation / formatting.

An injectable *extra-rule hook* lets callers register additional
:class:`Rule` detectors without touching this module.

The pipeline has three stages, mirroring the CAP-083 acceptance line -- *apply
scanning to every generated change and feed confirmed findings back into
generation*:

1. **scan** -- :meth:`ChangeSecurityScanner.scan` runs every rule over each
   edited file and returns raw :class:`Finding` objects (each carries a
   ``confidence`` and, initially, ``confirmed=False``).
2. **confirm** -- :meth:`ChangeSecurityScanner.confirm` filters out
   suppressed / false-positive-marked findings (inline ``# nosec`` markers or
   explicit suppression fingerprints) and anything below a confidence floor, so
   only genuinely *confirmed* findings proceed.
3. **feed back** -- :meth:`ChangeSecurityScanner.build_directives` turns each
   confirmed finding into a structured :class:`RegenerationDirective` naming the
   ``file:line``, the rule violated, and a concrete fix instruction the next
   generation pass should apply.

A change with any confirmed finding is marked **not clean**
(:attr:`ChangeScanResult.clean` is ``False``), which blocks acceptance until the
findings are addressed.

Everything here is deterministic: no randomness, no clock, no network, no
repository access -- only the edited content handed in.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

__all__ = [
    "Confidence",
    "FileEdit",
    "GeneratedChange",
    "Finding",
    "RegenerationDirective",
    "Rule",
    "RuleContext",
    "RuleMatch",
    "ChangeScanResult",
    "ChangeSecurityScanner",
    "main",
]


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


class Confidence(str, Enum):
    """Ordered confidence level for a finding."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_CONF_ORDER: dict[Confidence, int] = {
    Confidence.LOW: 0,
    Confidence.MEDIUM: 1,
    Confidence.HIGH: 2,
}

_SCANNABLE_SUFFIXES = frozenset({".py", ".pyi"})
_INLINE_SUPPRESS_MARKER = "# nosec"


# ---------------------------------------------------------------------------
# Change model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileEdit:
    """A single edited file in a generated change: its path and post-edit body.

    The scan operates on ``new_content`` -- the content the generator produced
    for this file -- which is the natural unit for an ``ast`` analysis.
    """

    path: str
    new_content: str

    @property
    def is_scannable(self) -> bool:
        return Path(self.path).suffix.lower() in _SCANNABLE_SUFFIXES


@dataclass(frozen=True)
class GeneratedChange:
    """A generated change: the ordered set of file edits it introduces."""

    edits: tuple[FileEdit, ...] = ()

    @classmethod
    def from_mapping(cls, files: Mapping[str, str]) -> GeneratedChange:
        """Build a change from a ``{path: new_content}`` mapping.

        Edits are ordered by path so scanning is deterministic regardless of
        the mapping's iteration order.
        """
        edits = tuple(FileEdit(path=path, new_content=files[path]) for path in sorted(files))
        return cls(edits=edits)


# ---------------------------------------------------------------------------
# Findings and directives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """A single security finding located at ``file:line`` in a generated change."""

    rule_id: str
    file: str
    line: int
    col: int
    message: str
    confidence: Confidence
    snippet: str
    fix_hint: str
    inline_suppressed: bool = False
    confirmed: bool = False

    @property
    def fingerprint(self) -> str:
        """Stable identity ``file:line:rule_id`` used for suppression matching."""
        return f"{self.file}:{self.line}:{self.rule_id}"

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "message": self.message,
            "confidence": self.confidence.value,
            "snippet": self.snippet,
            "inline_suppressed": self.inline_suppressed,
            "confirmed": self.confirmed,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class RegenerationDirective:
    """A structured instruction fed back into the next generation pass.

    It names exactly where the confirmed defect is (``file`` + ``line``), the
    rule violated, and a concrete fix the generator should apply.
    """

    file: str
    line: int
    rule_id: str
    finding_message: str
    fix_instruction: str

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}"

    def as_prompt(self) -> str:
        """Render the directive as a single instruction line for the generator."""
        return f"[{self.rule_id}] {self.file}:{self.line}: {self.finding_message} Fix: {self.fix_instruction}"

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "rule_id": self.rule_id,
            "finding_message": self.finding_message,
            "fix_instruction": self.fix_instruction,
            "location": self.location,
            "prompt": self.as_prompt(),
        }


@dataclass(frozen=True)
class ChangeScanResult:
    """Full result of scanning + confirming a generated change."""

    findings: tuple[Finding, ...] = ()
    confirmed: tuple[Finding, ...] = ()
    directives: tuple[RegenerationDirective, ...] = ()
    files_scanned: int = 0

    @property
    def clean(self) -> bool:
        """A change is clean iff it has no confirmed findings."""
        return not self.confirmed

    def to_dict(self) -> dict[str, object]:
        return {
            "clean": self.clean,
            "files_scanned": self.files_scanned,
            "findings": [f.to_dict() for f in self.findings],
            "confirmed": [f.to_dict() for f in self.confirmed],
            "directives": [d.to_dict() for d in self.directives],
        }


# ---------------------------------------------------------------------------
# Rule plumbing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleContext:
    """Everything a detector needs about one edited file."""

    path: str
    source: str
    tree: ast.Module
    lines: tuple[str, ...]

    def line_text(self, lineno: int) -> str:
        if 1 <= lineno <= len(self.lines):
            return self.lines[lineno - 1]
        return ""


@dataclass(frozen=True)
class RuleMatch:
    """A raw detector hit; ``message``/``confidence`` may override rule defaults."""

    line: int
    col: int = 0
    message: str | None = None
    confidence: Confidence | None = None


@dataclass(frozen=True)
class Rule:
    """A named security rule: a detector plus its metadata and default fix hint."""

    rule_id: str
    description: str
    fix_hint: str
    confidence: Confidence
    detector: Callable[[RuleContext], Iterable[RuleMatch]]


# ---------------------------------------------------------------------------
# Built-in detectors (deterministic, ast-based)
# ---------------------------------------------------------------------------

_SECRET_NAME_RE = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|apikey|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|auth[_-]?token)",
    re.IGNORECASE,
)
_SECRET_PLACEHOLDERS = frozenset(
    {"", "changeme", "change_me", "your_key_here", "xxx", "todo", "none", "null", "example"}
)
# High-signal literal shapes that are almost certainly real credentials.
_SECRET_LITERAL_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),  # PEM private key
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),  # GitHub token
    re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),  # Slack token
    re.compile(r"sk-[0-9A-Za-z]{16,}"),  # OpenAI-style secret key
)
_MIN_SECRET_LEN = 6

_SQL_KEYWORD_RE = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|WHERE|FROM|INTO)\b", re.IGNORECASE)


def _string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _target_names(node: ast.AST) -> list[tuple[str, int, int]]:
    """Return ``(name, line, col)`` for simple assignment targets."""
    out: list[tuple[str, int, int]] = []
    if isinstance(node, ast.Name):
        out.append((node.id, node.lineno, node.col_offset))
    elif isinstance(node, ast.Attribute):
        out.append((node.attr, node.lineno, node.col_offset))
    return out


def _looks_like_secret_literal(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_LITERAL_RES)


def _detect_secrets(ctx: RuleContext) -> list[RuleMatch]:
    matches: list[RuleMatch] = []
    for node in ast.walk(ctx.tree):
        # (a) name = "literal"  where the name looks secret-ish
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = getattr(node, "value", None)
            literal = _string_value(value) if value is not None else None
            if literal is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for name, line, col in _target_names(target):
                        if (
                            _SECRET_NAME_RE.search(name)
                            and len(literal) >= _MIN_SECRET_LEN
                            and literal.strip().lower() not in _SECRET_PLACEHOLDERS
                        ):
                            matches.append(
                                RuleMatch(
                                    line=line,
                                    col=col,
                                    message=f"hardcoded credential assigned to {name!r}",
                                    confidence=Confidence.MEDIUM,
                                )
                            )
        # (b) foo(password="literal")
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg is None:
                    continue
                literal = _string_value(kw.value)
                if (
                    literal is not None
                    and _SECRET_NAME_RE.search(kw.arg)
                    and len(literal) >= _MIN_SECRET_LEN
                    and literal.strip().lower() not in _SECRET_PLACEHOLDERS
                ):
                    matches.append(
                        RuleMatch(
                            line=kw.value.lineno,
                            col=kw.value.col_offset,
                            message=f"hardcoded credential passed as {kw.arg!r}",
                            confidence=Confidence.MEDIUM,
                        )
                    )
        # (c) any string literal that matches a known credential shape
        literal = _string_value(node)
        if literal is not None and _looks_like_secret_literal(literal):
            matches.append(
                RuleMatch(
                    line=node.lineno,
                    col=node.col_offset,
                    message="string literal matches a known credential format",
                    confidence=Confidence.HIGH,
                )
            )
    return matches


def _detect_eval_exec(ctx: RuleContext) -> list[RuleMatch]:
    matches: list[RuleMatch] = []
    for node in ast.walk(ctx.tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
            matches.append(
                RuleMatch(
                    line=node.lineno,
                    col=node.col_offset,
                    message=f"dynamic code execution via {node.func.id}()",
                )
            )
    return matches


def _detect_shell_true(ctx: RuleContext) -> list[RuleMatch]:
    matches: list[RuleMatch] = []
    for node in ast.walk(ctx.tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                matches.append(
                    RuleMatch(
                        line=node.lineno,
                        col=node.col_offset,
                        message="subprocess invoked with shell=True",
                    )
                )
    return matches


def _detect_pickle_loads(ctx: RuleContext) -> list[RuleMatch]:
    matches: list[RuleMatch] = []
    # Track `from pickle import loads` style bare imports.
    bare_loads = False
    for node in ast.walk(ctx.tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"pickle", "cPickle"}:
            for alias in node.names:
                if alias.name == "loads":
                    bare_loads = True
    for node in ast.walk(ctx.tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        dotted_loads = (
            isinstance(func, ast.Attribute)
            and func.attr == "loads"
            and isinstance(func.value, ast.Name)
            and func.value.id in {"pickle", "cPickle"}
        )
        bare_call = bare_loads and isinstance(func, ast.Name) and func.id == "loads"
        if dotted_loads or bare_call:
            matches.append(
                RuleMatch(
                    line=node.lineno,
                    col=node.col_offset,
                    message="unsafe deserialization via pickle.loads",
                )
            )
    return matches


def _flatten_add(node: ast.BinOp) -> list[ast.AST]:
    operands: list[ast.AST] = []

    def _walk(n: ast.AST) -> None:
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            _walk(n.left)
            _walk(n.right)
        else:
            operands.append(n)

    _walk(node)
    return operands


def _has_sql_keyword(node: ast.AST) -> bool:
    value = _string_value(node)
    return bool(value and _SQL_KEYWORD_RE.search(value))


def _is_dynamic(node: ast.AST) -> bool:
    return not (isinstance(node, ast.Constant))


def _detect_sql_concat(ctx: RuleContext) -> list[RuleMatch]:
    matches: list[RuleMatch] = []
    for node in ast.walk(ctx.tree):
        hit = False
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            operands = _flatten_add(node)
            if any(_has_sql_keyword(op) for op in operands) and any(_is_dynamic(op) for op in operands):
                hit = True
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            # "SELECT ... %s" % value
            if _has_sql_keyword(node.left):
                hit = True
        elif isinstance(node, ast.JoinedStr):
            # f"SELECT ... {value}"
            has_dynamic = any(isinstance(v, ast.FormattedValue) for v in node.values)
            has_sql = any(
                bool(_string_value(v) and _SQL_KEYWORD_RE.search(_string_value(v) or "")) for v in node.values
            )
            if has_dynamic and has_sql:
                hit = True
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
            and _has_sql_keyword(node.func.value)
        ):
            hit = True
        if hit:
            matches.append(
                RuleMatch(
                    line=node.lineno,
                    col=node.col_offset,
                    message="SQL query built by string concatenation/formatting",
                )
            )
    return matches


BUILTIN_RULES: tuple[Rule, ...] = (
    Rule(
        rule_id="hardcoded-secret",
        description="Hardcoded secret or credential literal in source.",
        fix_hint=(
            "Remove the hardcoded credential and load it at runtime from an "
            "environment variable or secret manager instead of embedding it in source."
        ),
        confidence=Confidence.MEDIUM,
        detector=_detect_secrets,
    ),
    Rule(
        rule_id="eval-exec",
        description="Dynamic code execution via eval() or exec().",
        fix_hint=(
            "Remove the eval()/exec() call; replace dynamic code execution with an "
            "explicit dispatch table, or use ast.literal_eval for pure data."
        ),
        confidence=Confidence.HIGH,
        detector=_detect_eval_exec,
    ),
    Rule(
        rule_id="shell-true",
        description="subprocess call with shell=True.",
        fix_hint=(
            "Do not pass shell=True; pass the command as an argument list so the OS "
            "handles quoting, or strictly validate and escape any interpolated input."
        ),
        confidence=Confidence.HIGH,
        detector=_detect_shell_true,
    ),
    Rule(
        rule_id="pickle-loads",
        description="Unsafe deserialization via pickle.loads.",
        fix_hint=(
            "Do not deserialize untrusted data with pickle.loads; use a safe format "
            "such as json, or verify the data's provenance/signature before loading."
        ),
        confidence=Confidence.HIGH,
        detector=_detect_pickle_loads,
    ),
    Rule(
        rule_id="sql-injection",
        description="SQL query built by string concatenation/formatting.",
        fix_hint=(
            "Do not build SQL by concatenation or string formatting; use a "
            "parameterized query with placeholder binding for all user-supplied values."
        ),
        confidence=Confidence.HIGH,
        detector=_detect_sql_concat,
    ),
)


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class ChangeSecurityScanner:
    """Scan every generated change and feed confirmed findings back into generation.

    Parameters
    ----------
    extra_rules:
        Additional :class:`Rule` detectors, applied alongside the built-in set.
        This is the injectable extra-rule hook -- callers extend coverage without
        editing this module.
    min_confidence:
        Findings below this confidence are not confirmed during
        :meth:`confirm` unless a stricter floor is passed there.
    """

    def __init__(
        self,
        extra_rules: Sequence[Rule] = (),
        *,
        min_confidence: Confidence = Confidence.LOW,
    ) -> None:
        self._rules: tuple[Rule, ...] = tuple(BUILTIN_RULES) + tuple(extra_rules)
        self._min_confidence = min_confidence

    @property
    def rules(self) -> tuple[Rule, ...]:
        return self._rules

    # -- stage 1: scan ------------------------------------------------------

    def scan(self, change: GeneratedChange) -> list[Finding]:
        """Run every rule over each edited file; return raw findings.

        Only the files in *change* are analyzed (the scan targets the change,
        not the repository).  Results are sorted deterministically by
        ``(file, line, col, rule_id)``.
        """
        findings: list[Finding] = []
        for edit in change.edits:
            if not edit.is_scannable:
                continue
            ctx = self._parse(edit)
            if ctx is None:
                continue
            for rule in self._rules:
                for match in rule.detector(ctx):
                    line = match.line
                    line_text = ctx.line_text(line)
                    findings.append(
                        Finding(
                            rule_id=rule.rule_id,
                            file=edit.path,
                            line=line,
                            col=match.col,
                            message=match.message or rule.description,
                            confidence=match.confidence or rule.confidence,
                            snippet=line_text.strip()[:200],
                            fix_hint=rule.fix_hint,
                            inline_suppressed=_INLINE_SUPPRESS_MARKER in line_text.lower(),
                        )
                    )
        return self._dedupe_and_sort(findings)

    @staticmethod
    def _parse(edit: FileEdit) -> RuleContext | None:
        try:
            tree = ast.parse(edit.new_content, filename=edit.path)
        except (SyntaxError, ValueError):
            # A change that does not parse cannot be analyzed by the ast rules;
            # it is not a security finding on its own, so skip the file.
            return None
        return RuleContext(
            path=edit.path,
            source=edit.new_content,
            tree=tree,
            lines=tuple(edit.new_content.splitlines()),
        )

    @staticmethod
    def _dedupe_and_sort(findings: Iterable[Finding]) -> list[Finding]:
        seen: dict[tuple[str, int, str], Finding] = {}
        for finding in findings:
            key = (finding.file, finding.line, finding.rule_id)
            # Keep the highest-confidence variant on a collision (stable).
            existing = seen.get(key)
            if existing is None or _CONF_ORDER[finding.confidence] > _CONF_ORDER[existing.confidence]:
                seen[key] = finding
        return sorted(
            seen.values(),
            key=lambda f: (f.file, f.line, f.col, f.rule_id),
        )

    # -- stage 2: confirm ---------------------------------------------------

    def confirm(
        self,
        findings: Iterable[Finding],
        suppressions: Iterable[str] = (),
        *,
        min_confidence: Confidence | None = None,
    ) -> list[Finding]:
        """Filter *findings* down to the confirmed set.

        A finding is dropped when it is suppressed -- either flagged inline with
        a ``# nosec`` marker or matched by an explicit suppression fingerprint
        (``file:line:rule_id``) -- or when its confidence is below the floor.
        Surviving findings are returned with ``confirmed=True``.
        """
        floor = min_confidence if min_confidence is not None else self._min_confidence
        suppressed_keys = set(suppressions)
        confirmed: list[Finding] = []
        for finding in findings:
            if finding.inline_suppressed or finding.fingerprint in suppressed_keys:
                continue
            if _CONF_ORDER[finding.confidence] < _CONF_ORDER[floor]:
                continue
            confirmed.append(replace(finding, confirmed=True))
        return confirmed

    # -- stage 3: feed back into generation ---------------------------------

    @staticmethod
    def build_directives(confirmed: Iterable[Finding]) -> list[RegenerationDirective]:
        """Turn confirmed findings into structured regeneration directives."""
        directives: list[RegenerationDirective] = []
        for finding in confirmed:
            directives.append(
                RegenerationDirective(
                    file=finding.file,
                    line=finding.line,
                    rule_id=finding.rule_id,
                    finding_message=finding.message,
                    fix_instruction=finding.fix_hint,
                )
            )
        return directives

    # -- full pipeline ------------------------------------------------------

    def evaluate_change(
        self,
        change: GeneratedChange,
        suppressions: Iterable[str] = (),
        *,
        min_confidence: Confidence | None = None,
    ) -> ChangeScanResult:
        """Run the full scan -> confirm -> feed-back pipeline on *change*.

        The returned :class:`ChangeScanResult` is ``clean`` iff there are no
        confirmed findings; otherwise it carries the regeneration directives the
        next generation pass must satisfy before the change can be accepted.
        """
        findings = self.scan(change)
        confirmed = self.confirm(findings, suppressions, min_confidence=min_confidence)
        directives = self.build_directives(confirmed)
        files_scanned = sum(1 for edit in change.edits if edit.is_scannable)
        return ChangeScanResult(
            findings=tuple(findings),
            confirmed=tuple(confirmed),
            directives=tuple(directives),
            files_scanned=files_scanned,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Scan files as a generated change; print JSON, exit 1 if not clean."""
    parser = argparse.ArgumentParser(
        prog="python -m thomas.security.change_scanner",
        description="Scan a generated change for security defects and emit regeneration directives.",
    )
    parser.add_argument("paths", nargs="+", help="files that make up the generated change")
    parser.add_argument(
        "--suppress",
        action="append",
        default=[],
        metavar="FILE:LINE:RULE",
        help="suppression fingerprint to treat as a confirmed false positive",
    )
    args = parser.parse_args(argv)

    files: dict[str, str] = {}
    for path in args.paths:
        try:
            files[path] = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            parser.error(f"cannot read {path}: {exc}")
    change = GeneratedChange.from_mapping(files)
    result = ChangeSecurityScanner().evaluate_change(change, suppressions=args.suppress)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.clean else 1


if __name__ == "__main__":
    sys.exit(main())
