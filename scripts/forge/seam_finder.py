"""Where an oversized Python file wants to be cut, read from its own references.

The monolith guard measures size. This reads structure: every top-level
definition is a unit, every name one unit uses from another is an edge, and a
seam is a point in the file's own order where the edges between the two sides
drop to zero, or as close to it as the file allows. Helpers both sides lean on
are reported as shared, to move into one module rather than be copied. The
result is advice for whoever splits the file, never a verdict.

Usage: python scripts/forge/seam_finder.py <file.py> [--limit 800] [--json]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_LIMIT = 800
_MIN_FILL = 0.5  # a part is not cut before it is at least this full


@dataclass
class Unit:
    name: str
    start: int
    end: int
    refs: set[str] = field(default_factory=set)
    fixture: bool = False
    node: Any = None

    @property
    def lines(self) -> int:
        return self.end - self.start + 1


@dataclass
class Part:
    names: list[str]
    start: int
    end: int
    lines: int
    needs: list[str] = field(default_factory=list)


@dataclass
class Report:
    path: str
    total_lines: int
    limit: int
    header_lines: int
    parts: list[Part]
    shared: list[str]
    crossings: int
    budget: int = 0
    oversized: list[str] = field(default_factory=list)
    wrapped: bool = False
    inner: dict[str, Report] = field(default_factory=dict)
    template_lines: int = 0

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "total_lines": self.total_lines,
            "limit": self.limit,
            "header_lines": self.header_lines,
            "budget": self.budget,
            "parts": [p.__dict__ for p in self.parts],
            "shared": self.shared,
            "crossings": self.crossings,
            "oversized": self.oversized,
            "inner": {k: v.to_dict() for k, v in self.inner.items()},
        }

    def render(self) -> str:
        over = self.total_lines - self.limit
        standing = f"over the limit by {over}" if over > 0 else "under the limit"
        out = [f"{self.path}: {self.total_lines} lines, {standing} ({self.limit}), header {self.header_lines}"]
        if self.wrapped:
            out.append("the file is one closure; units were read one level down, inside it")
        if self.template_lines:
            out.append(
                f"template (markup, styles) {self.template_lines} lines: not code, not cut here; "
                "the script blocks below are the code"
            )
        if not self.parts:
            out.append(
                "no units found: this tool reads functions, classes and const bindings, and this file "
                "has none at its top level or one level down (a template or data file, most likely)"
            )
            return "\n".join(out)
        for name in self.oversized:
            lines = next((p.lines for p in self.parts if p.names == [name]), None)
            size = f"{lines} lines" if lines is not None else "more than the budget"
            tail = (
                "read below by its methods"
                if name in self.inner
                else "this tool cuts between top-level definitions only, so the cut has to be inside it"
            )
            out.append(f"{name} is {size} by itself, over the {self.budget}-line budget: {tail}")
        for name, sub in self.inner.items():
            out.append(f"inside {name}, by its methods (self.<name> is the edge):")
            out.extend("  " + line for line in sub.render().splitlines()[1:])
        if len(self.parts) == 1 and not self.shared:
            out.append(
                "no seam between definitions fits: trim, or cut inside the largest unit"
                if over > 0
                else "one part; nothing to cut"
            )
            return "\n".join(out)
        for i, p in enumerate(self.parts, 1):
            out.append(f"part {i}: lines {p.start}-{p.end} ({p.lines} lines): {', '.join(p.names)}")
            if p.needs:
                out.append(f"  needs from another part: {', '.join(p.needs)}")
        if self.shared:
            out.append(f"shared, move to one helper module: {', '.join(self.shared)}")
        out.append(f"crossings left: {self.crossings}")
        return "\n".join(out)


def _is_fixture(node: ast.AST) -> bool:
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr == "fixture":
            return True
        if isinstance(target, ast.Name) and target.id == "fixture":
            return True
    return False


def _unit_start(node: ast.AST) -> int:
    decos = getattr(node, "decorator_list", [])
    return min([node.lineno] + [d.lineno for d in decos])


_JS_UNIT = re.compile(
    r"^(?:export\s+)?(?:(?:async\s+)?function\s*\*?\s*(?P<fn>[A-Za-z_$][\w$]*)\s*\("
    r"|class\s+(?P<cls>[A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s+(?P<var>[A-Za-z_$][\w$]*)\s*=)"
)
_JS_SUFFIXES = {".js", ".mjs", ".cjs"}


def _regex_may_start(emitted: list[str]) -> bool:
    """A slash begins a regex literal when what precedes it cannot end an operand."""
    for ch in reversed(emitted):
        if ch.isspace():
            continue
        return ch in "(,=:[!&|?{};+-*%<>~^"
    return True


def _strip_js_noise(line: str, quote: str | None = None) -> tuple[str, str | None]:
    """Drop string literals and line comments so braces and names inside them do not count.

    ``quote`` is the literal still open from the previous line (a template
    literal spans lines); the open quote at the end of this line is returned.
    """
    out, i = [], 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif line.startswith("//", i):
            break
        elif line.startswith("/*", i):
            end = line.find("*/", i + 2)
            if end < 0:
                break  # the collector handles comments that span lines
            i = end + 2
            continue
        elif ch == "/" and _regex_may_start(out):
            # a regex literal: skip to its unescaped closing slash, outside [...]
            j, in_class = i + 1, False
            while j < len(line):
                c = line[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    break
                j += 1
            i = j + 1
            continue
        else:
            out.append(ch)
        i += 1
    if quote in ("'", '"'):
        quote = None  # ordinary strings end with the line
    return "".join(out), quote


def _collect_js_units(source: str, base_depth: int = 0) -> list[Unit]:
    """Function declarations, classes and const/let/var bindings at ``base_depth`` braces deep.

    Depth 0 is the file's top level; depth 1 is the inside of the one closure
    most of Thomas's web modules wrap themselves in.
    """
    units: list[Unit] = []
    depth = 0
    open_unit: Unit | None = None
    bodies: dict[str, list[str]] = {}
    in_block_comment = False
    open_quote: str | None = None
    for n, raw in enumerate(source.split("\n"), 1):
        line = raw
        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
                line = line.split("*/", 1)[1]
            else:
                continue
        if "/*" in line and "*/" not in line.split("/*", 1)[1]:
            in_block_comment = True
            line = line.split("/*", 1)[0]
        clean, open_quote = _strip_js_noise(line, open_quote)
        if depth == base_depth and open_unit is None:
            m = _JS_UNIT.match(clean.strip())
            if m:
                name = m.group("fn") or m.group("cls") or m.group("var")
                open_unit = Unit(name, n, n)
                bodies[name] = []
        if open_unit is not None:
            bodies[open_unit.name].append(clean)
        depth += clean.count("{") - clean.count("}")
        if (
            open_unit is not None
            and depth <= base_depth
            and (clean.rstrip().endswith((";", "}", ")")) or "{" not in clean)
        ):
            open_unit.end = n
            units.append(open_unit)
            open_unit = None
    if open_unit is not None:
        open_unit.end = source.count("\n") + 1
        units.append(open_unit)
    names = {u.name for u in units}
    for u in units:
        body = "\n".join(bodies.get(u.name, []))
        u.refs = {m for m in re.findall(r"[A-Za-z_$][\w$]*", body) if m in names and m != u.name}
    return units


_HTML_SUFFIXES = {".html", ".htm"}
_SCRIPT_OPEN = re.compile(r"<script\b[^>]*>", re.I)
_SCRIPT_CLOSE = re.compile(r"</script\s*>", re.I)


def _html_script_source(source: str) -> tuple[str, int]:
    """The page with everything outside ``<script>`` blocks blanked, line numbers kept.

    Returns that masked source and the number of non-blank template lines
    (markup, styles) the tool has no business cutting.
    """
    out: list[str] = []
    template = 0
    inside = False
    for raw in source.split("\n"):
        line = raw
        if not inside:
            m = _SCRIPT_OPEN.search(line)
            if m:
                if line[: m.start()].strip():
                    template += 1
                inside = True
                line = line[m.end() :]
            else:
                if line.strip():
                    template += 1
                out.append("")
                continue
        close = _SCRIPT_CLOSE.search(line)
        if close:
            out.append(line[: close.start()])
            if line[close.end() :].strip():
                template += 1
            inside = False
        else:
            out.append(line)
    return "\n".join(out), template


def _collect_units(tree: ast.Module) -> list[Unit]:
    units: list[Unit] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            units.append(Unit(node.name, _unit_start(node), node.end_lineno or node.lineno, fixture=_is_fixture(node), node=node))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if names:
                units.append(Unit(names[0], node.lineno, node.end_lineno or node.lineno))
    return units


def _references(tree: ast.Module, units: list[Unit]) -> None:
    by_name = {u.name: u for u in units}
    fixtures = {u.name for u in units if u.fixture}
    by_start = {u.start: u for u in units}
    for node in tree.body:
        unit = by_start.get(_unit_start(node))
        if unit is None:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in by_name and sub.id != unit.name:
                unit.refs.add(sub.id)
            elif isinstance(sub, ast.arg) and sub.arg in fixtures and sub.arg != unit.name:
                unit.refs.add(sub.arg)


def _crossing_cost(
    left: list[Unit], right: list[Unit], shared: set[str], referrers: dict[str, set[str]]
) -> int:
    """Edges across the cut, plus half a point per helper whose users it separates.

    A crossing is a real dependency between two files; a separated helper only
    means the shared module earns its keep. The half weight lets a cut that
    keeps a helper shared beat one that leaves a dependency dangling.
    """
    left_names = {u.name for u in left}
    right_names = {u.name for u in right}
    cost = 0.0
    for u in left:
        cost += len((u.refs & right_names) - shared)
    for u in right:
        cost += len((u.refs & left_names) - shared)
    for name in shared:
        users = referrers.get(name, set())
        if users & left_names and users & right_names:
            cost += 0.5
    return cost


def _segment(
    units: list[Unit], limit: int, shared: set[str], referrers: dict[str, set[str]]
) -> list[list[Unit]]:
    """Greedy: fill a part to at least half the limit, then cut where the fewest edges cross."""
    seq = [u for u in units if u.name not in shared]
    parts: list[list[Unit]] = []
    start = 0
    while start < len(seq):
        size = 0
        furthest = start
        for j in range(start, len(seq)):
            if size + seq[j].lines > limit and j > start:
                break
            size += seq[j].lines
            furthest = j
        if furthest == len(seq) - 1:
            parts.append(seq[start:])
            break
        best_k, best_cost = furthest + 1, None
        filled = 0
        for k in range(start + 1, furthest + 2):
            filled += seq[k - 1].lines
            if filled < limit * _MIN_FILL and k < furthest + 1:
                continue
            cost = _crossing_cost(seq[start:k], seq[k:], shared, referrers)
            if best_cost is None or cost <= best_cost:
                best_k, best_cost = k, cost
        parts.append(seq[start:best_k])
        start = best_k
    return parts


def _referrers(units: list[Unit]) -> dict[str, set[str]]:
    referrers: dict[str, set[str]] = {}
    for u in units:
        for r in u.refs:
            referrers.setdefault(r, set()).add(u.name)
    return referrers


def _still_shared(parts: list[list[Unit]], shared: set[str], referrers: dict[str, set[str]]) -> set[str]:
    """A candidate stays shared only while its users sit in at least two parts.

    Users that are themselves shared do not count: a helper that only helpers
    use travels with them to the helper module.
    """
    part_of = {u.name: i for i, p in enumerate(parts) for u in p}
    keep: set[str] = set()
    for name in shared:
        homes = {part_of[user] for user in referrers.get(name, ()) if user in part_of}
        if len(homes) >= 2:
            keep.add(name)
    return keep


def _with_what_helpers_use(shared: set[str], units: list[Unit]) -> set[str]:
    """A helper module must carry what its helpers use, transitively."""
    by_name = {u.name: u for u in units}
    out = set(shared)
    frontier = list(shared)
    while frontier:
        name = frontier.pop()
        for ref in by_name[name].refs if name in by_name else ():
            if ref in by_name and ref not in out:
                out.add(ref)
                frontier.append(ref)
    return out


def _class_method_units(cls: ast.ClassDef) -> list[Unit]:
    """A class's methods as units; ``self.<name>`` to another method is the edge."""
    methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    names = {m.name for m in methods}
    # unittest runs these for every test without any test naming them, so
    # every other method is treated as using them: they come out shared.
    lifecycle = names & {"setUp", "tearDown", "setUpClass", "tearDownClass", "asyncSetUp", "asyncTearDown"}
    units: list[Unit] = []
    for m in methods:
        unit = Unit(m.name, _unit_start(m), m.end_lineno or m.lineno, fixture=_is_fixture(m), node=m)
        if m.name not in lifecycle:
            unit.refs |= lifecycle
        for sub in ast.walk(m):
            if (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id in ("self", "cls")
                and sub.attr in names
                and sub.attr != m.name
            ):
                unit.refs.add(sub.attr)
        units.append(unit)
    return units


def _build_report(path: str, units: list[Unit], total: int, limit_lines: int, header: int, wrapped: bool) -> Report:
    referrers = _referrers(units)
    # Every part carries the file's header plus one import line for the
    # helper module, so that is not room the parts can use.
    budget = max(1, limit_lines - header - 1)
    # Anything two or more units use is a helper candidate: it leaves the
    # sequence before the cut is chosen, and comes home only if every user
    # lands in the same part.
    shared = {name for name, users in referrers.items() if len(users) >= 2}
    parts = _segment(units, budget, shared, referrers)
    for _ in range(4):
        keep = _still_shared(parts, shared, referrers) if len(parts) > 1 else set()
        if keep == shared:
            break
        shared = keep
        parts = _segment(units, budget, shared, referrers)
    shared = _with_what_helpers_use(shared, units)
    parts = _segment(units, budget, shared, referrers)
    part_of = {u.name: i for i, p in enumerate(parts) for u in p}
    report_parts: list[Part] = []
    crossings = 0
    for i, p in enumerate(parts):
        needs = sorted({r for u in p for r in u.refs if r not in shared and part_of.get(r, i) != i})
        crossings += len(needs)
        report_parts.append(Part([u.name for u in p], p[0].start, p[-1].end, sum(u.lines for u in p), needs))
    oversized = [u.name for u in units if u.lines > budget]
    report = Report(path, total, limit_lines, header, report_parts, sorted(shared), crossings, budget, oversized, wrapped)
    for u in units:
        if u.lines > budget and isinstance(u.node, ast.ClassDef):
            methods = _class_method_units(u.node)
            if len(methods) >= 2:
                class_header = methods[0].start - u.start
                report.inner[u.name] = _build_report(f"{path}::{u.name}", methods, u.lines, limit_lines, class_header, False)
    return report


def find_seams(path: str | Path, limit_lines: int = DEFAULT_LIMIT) -> Report:
    path = Path(path)
    source = path.read_text(encoding="utf-8")
    total = source.count("\n") + (0 if source.endswith("\n") else 1)
    wrapped = False
    template = 0
    suffix = path.suffix.lower()
    if suffix in _JS_SUFFIXES or suffix in _HTML_SUFFIXES:
        script = source
        if suffix in _HTML_SUFFIXES:
            script, template = _html_script_source(source)
        units = _collect_js_units(script)
        inner = _collect_js_units(script, base_depth=1)
        # A page or module wrapped in one closure keeps a few constants at the top
        # level and everything real one brace down: read the depth whose units
        # cover more of the code, not the depth with more of them.
        if sum(u.lines for u in inner) > sum(u.lines for u in units):
            units, wrapped = inner, True
    else:
        tree = ast.parse(source)
        units = _collect_units(tree)
        _references(tree, units)
    # A page's parts become script files of their own, so its markup is not a header they carry.
    header = 0 if template else ((units[0].start - 1) if units else total)
    report = _build_report(str(path), units, total, limit_lines, header, wrapped)
    report.template_lines = template
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Where an oversized Python file wants to be cut.")
    parser.add_argument("path")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = find_seams(args.path, args.limit)
    print(json.dumps(report.to_dict(), indent=2) if args.json else report.render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
