"""The repo's size rule, as one rule, read from both registers that write it down.

Thomas's own repo states its size limit twice, and the two do not agree about who is exempt:

* ``docs/monolith_guard_baseline.json`` -- read by ``scripts/forge/gates/monolith_guard.py``, the gate that
  runs at every commit. A changed file over ``unbaselined_soft_limit_lines`` (800) fails unless it is listed
  under ``allowed_large_files``, where it gets its own ``max_lines`` and ``max_growth_lines``.
* ``thomas/_architecture.py`` -- read by ``tests/test_architecture.py::test_debt_trending``, which runs over
  the WHOLE tree rather than the changed files. A ``.py`` file under ``thomas/`` over
  ``RULES["max_new_file_lines"]`` (also 800) fails unless some module's ``debt`` note records it in the form
  ``<file>.py exceeds <N> lines``.

Same number, two exemption lists. On 2026-09-25 that gap cost a landed fix and every commit after it:
``thomas/agent/loop_execution.py`` carries an ``allowed_large_files`` waiver (``max_lines`` 1100,
``max_growth_lines`` 130) and is NOT recorded in the ``agent`` module's debt note, which names only
``swarm.py``. A change that took it over 800 therefore passed its hand-in size check
(:func:`thomas.server.green_handoff.size_problems`, which read only the baseline) and then failed
``test_debt_trending`` for every later commit until the file was split back under 800.

So this module is the one rule, and the hand-in check reads it: a file must satisfy BOTH registers, in both
directions. The second direction is the same gap mirrored -- ``test_health_annotations`` fails a debt note
that names a file that is GONE, or that calls a file oversized when it has been brought back under 800 -- so
trimming ``thomas/server/routes/work.py`` from 805 lines to 799 also passed the hand-in check and failed
every commit after it (:func:`stale_debt_problems`). Nothing here relaxes either gate -- a change that would
pass one and break the other now comes back to the team that wrote it (``thomas_project.ChangeTooLarge`` ->
a repair round) instead of landing and blocking everyone else.

Read from the green's OWN checkout, never from the running Thomas: a project may be changing these registers,
and the rule that judges it is the one in the source it produced. ``_architecture.py`` is parsed rather than
imported, for the same reason -- importing ``thomas._architecture`` would answer for the running copy.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

BASELINE = "docs/monolith_guard_baseline.json"
ARCHITECTURE = "thomas/_architecture.py"

# The monolith guard's own defaults (DEFAULT_HARD_LIMITS, waiver_policy), used when a register cannot be read.
# A register Thomas cannot read must not silently widen the rule.
_HARD_LIMITS = dict.fromkeys(("py", "js", "mjs", "cjs", "jsx", "ts", "tsx"), 1200) | {"css": 1600, "html": 1000}
_SOFT_LIMIT = 800
# Fallbacks for RULES["max_new_file_lines"] and RULES["forbidden_patterns"] + RULES["legacy_patterns"] --
# the filenames test_architecture.py does not measure at all, so this half must not measure them either.
# Both are read from the green's own _architecture.py when it can be parsed; these are what they say today.
_ARCHITECTURE_LIMIT = 800
_ARCHITECTURE_SKIP = ("tmp_*", "probe_*", "*_probe.*", "p[0-9][0-9][0-9]_*", "_architecture.py", "repl.py")
# Folders neither gate measures (monolith_guard.SKIP_DIR_NAMES, in the part a green's patch can reach).
SKIP_DIRS = frozenset({".git", ".venv", "__pycache__", "node_modules", "build", "dist", "runtime", "generated"})
# thomas/<module>/<file>.py exceeds <N> lines -- test_debt_trending's own pattern, so the same notes count.
_DEBT_SIZE = re.compile(r"([\w\-/]+\.py)\s+exceeds?\s+(\d+)\s+lines")
# Every .py a note names, however it names it -- test_health_annotations' own pattern, which is looser than
# the one above and is why the two halves of a debt note have to be read separately.
_DEBT_FILE = re.compile(r"([\w\-/]+\.py)")


@dataclass(frozen=True)
class SizeRule:
    """Both registers, resolved into the numbers a per-file verdict needs."""

    hard: dict[str, int]
    soft: int
    default_growth: int
    allowed: dict[str, Any]
    architecture_limit: int
    architecture_skip: tuple[str, ...]
    debt_recorded: frozenset[str]
    debt_named: frozenset[str]
    debt_oversize: frozenset[str]


def _whole(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return default


def line_count(text: str) -> int:
    return len(text.splitlines())


def _baseline(blue: Path) -> dict[str, Any]:
    try:
        loaded = json.loads((Path(blue) / BASELINE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _architecture_literal(blue: Path, name: str) -> dict[str, Any]:
    """``MODULES`` or ``RULES`` out of the green's ``_architecture.py``, by parsing, never by importing.

    Both are plain dict literals in that file. ``ast.literal_eval`` refuses anything that is not, so a
    register rewritten into something this cannot read answers ``{}`` and the caller falls back to the
    defaults above -- it never runs code out of a green.
    """
    try:
        tree = ast.parse((Path(blue) / ARCHITECTURE).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (SyntaxError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def debt_recorded(blue: Path) -> frozenset[str]:
    """Every file an ``_architecture.py`` debt note records a size for, as a repo-relative path.

    The key shape is ``test_debt_trending``'s: the module's own name joined to whatever the note spells,
    so ``server``'s ``routes/work.py exceeds 800 lines`` records ``thomas/server/routes/work.py``.
    """
    modules = _architecture_literal(blue, "MODULES")
    found: set[str] = set()
    for name, module in modules.items():
        if not isinstance(module, dict):
            continue
        for match in _DEBT_SIZE.finditer(str(module.get("debt") or "")):
            found.add(f"thomas/{name}/{match.group(1)}")
    return frozenset(found)


def debt_notes(blue: Path) -> dict[str, bool]:
    """Every file a debt note names -> whether that note calls it oversized.

    ``test_health_annotations`` reads the notes this way and not the way ``test_debt_trending`` does: it takes
    every ``.py`` path in a note (``_DEBT_FILE``), requires it to EXIST, and -- when the note's text contains
    "exceed" or "over" anywhere in it -- requires every file that note names to be over
    ``max_new_file_lines``. So the claim is made per note and inherited by each file in it, which is exactly
    how a team splitting one file in a note breaks the check for the others.
    """
    modules = _architecture_literal(blue, "MODULES")
    found: dict[str, bool] = {}
    for name, module in modules.items():
        if not isinstance(module, dict):
            continue
        note = str(module.get("debt") or "")
        claims = "exceed" in note.lower() or "over" in note.lower()
        for match in _DEBT_FILE.finditer(note):
            rel = f"thomas/{name}/{match.group(1)}"
            found[rel] = found.get(rel, False) or claims
    return found


def read_rule(blue: Path) -> SizeRule:
    """Both registers as they stand in this checkout."""
    baseline = _baseline(blue)
    hard = dict(_HARD_LIMITS)
    raw_limits = baseline.get("hard_limits")
    for ext, value in (raw_limits if isinstance(raw_limits, dict) else {}).items():
        hard[str(ext)] = _whole(value, hard.get(str(ext), 0))
    policy = baseline.get("waiver_policy") if isinstance(baseline.get("waiver_policy"), dict) else {}
    allowed = baseline.get("allowed_large_files") if isinstance(baseline.get("allowed_large_files"), dict) else {}
    rules = _architecture_literal(blue, "RULES")
    named = debt_notes(blue)
    return SizeRule(
        hard=hard,
        soft=_whole(policy.get("unbaselined_soft_limit_lines"), _SOFT_LIMIT),
        default_growth=max(0, _whole(policy.get("default_max_growth_lines"), 0)),
        allowed=allowed,
        architecture_limit=_whole(rules.get("max_new_file_lines"), _ARCHITECTURE_LIMIT),
        architecture_skip=_skip_patterns(rules),
        debt_recorded=debt_recorded(blue),
        debt_named=frozenset(named),
        debt_oversize=frozenset(rel for rel, claims in named.items() if claims),
    )


def _skip_patterns(rules: dict[str, Any]) -> tuple[str, ...]:
    """The filenames ``test_architecture.py`` does not measure, read from ``RULES`` where it reads them."""
    found = [
        str(pattern)
        for key in ("forbidden_patterns", "legacy_patterns")
        for pattern in (rules.get(key) if isinstance(rules.get(key), list) else [])
        if str(pattern).strip()
    ]
    return tuple(found) if found else _ARCHITECTURE_SKIP


def measured(rule: SizeRule, rel: str) -> bool:
    """Whether either gate measures this path at all."""
    if SKIP_DIRS.intersection(Path(rel).parts):
        return False
    return bool(rule.hard.get(Path(rel).suffix.lstrip(".").lower(), 0)) or _under_architecture(rule, rel)


def _under_architecture(rule: SizeRule, rel: str) -> bool:
    """Whether ``test_debt_trending`` measures this file: a ``.py`` under ``thomas/`` it does not skip."""
    posix = rel.replace("\\", "/")
    if not posix.startswith("thomas/") or not posix.endswith(".py"):
        return False
    name = Path(posix).name
    return not any(fnmatch(name, pattern) for pattern in rule.architecture_skip)


def file_problems(rule: SizeRule, rel: str, lines: int, before: int) -> list[str]:
    """Where one changed file breaks the rule, in words for the team that wrote it; [] when it keeps to it.

    ``before`` is the file's line count at the green's base, for the growth half of a baseline waiver.
    Both registers are checked, and both reasons are reported -- a team that hears only one of them fixes
    the file down to 1100 lines and is refused again at 800.
    """
    problems: list[str] = []
    limit = rule.hard.get(Path(rel).suffix.lstrip(".").lower(), 0)
    entry = rule.allowed.get(rel)
    if limit and (lines > limit or (rule.soft and lines > rule.soft)):
        if not isinstance(entry, dict):
            most = min(limit, rule.soft) if rule.soft else limit
            problems.append(f"{rel} has {lines} lines; a file not in allowed_large_files may have at most {most}")
        else:
            most = _whole(entry.get("max_lines"), limit)
            if lines > most:
                problems.append(f"{rel} has {lines} lines; its allowed_large_files entry allows {most}")
            growth = max(0, _whole(entry.get("max_growth_lines"), rule.default_growth))
            if lines - before > growth:
                # Named in full, like the line above it: "its entry" leaves a team hunting for which register
                # the number came from, and there are two.
                problems.append(f"{rel} grew by {lines - before} lines; its allowed_large_files entry allows {growth}")
    if lines > rule.architecture_limit and _under_architecture(rule, rel) and rel not in rule.debt_recorded:
        problems.append(
            f"{rel} has {lines} lines; no debt note in {ARCHITECTURE} records this file, and "
            f"tests/test_architecture.py fails any file under thomas/ over {rule.architecture_limit} lines "
            "that none does -- for every commit after this one, not just yours. Split it, or record it "
            "there as '<file>.py exceeds <N> lines' in its module's debt note. An allowed_large_files "
            f"waiver in {BASELINE} does not cover this half of the rule."
        )
    return problems


def stale_debt_problems(rule: SizeRule, rel: str, lines: int | None) -> list[str]:
    """The other direction of the architecture register: where this change makes a debt note FALSE.

    ``file_problems`` above checks one way round -- a file over the limit that no note records. The notes are
    also checked the other way, by ``tests/test_architecture.py::test_health_annotations``, which fails a note
    that names a file that does not exist, or that calls a file oversized when it is no longer over
    ``max_new_file_lines``. Both are states a change CREATES, and, like the first direction, both then fail for
    every later commit rather than only for the change that caused them.

    This is not a corner: trimming a debt-recorded file under 800 lines -- ``thomas/server/routes/work.py``
    from 805 to 799, say -- passed ``size_problems`` with ``[]`` and then failed every commit after it. Several
    debt-recorded files sit within a handful of lines of the limit, and ``_TEAM_NOTES`` tells a team to SPLIT
    an oversized file, which is the exact move that trips this.

    ``lines`` is None for a path the change leaves without a file: deleted, or renamed away.
    """
    posix = rel.replace("\\", "/")
    if posix not in rule.debt_named:
        return []
    if lines is None:
        return [
            f"{rel} is not in this change's tree any more, and a debt note in {ARCHITECTURE} still names it. "
            "tests/test_architecture.py::test_health_annotations fails a debt note that names a file that does "
            "not exist -- for every commit after this one, not just yours. Take it out of its module's debt "
            "note in this same change."
        ]
    if posix in rule.debt_oversize and lines <= rule.architecture_limit:
        return [
            f"{rel} has {lines} lines, and a debt note in {ARCHITECTURE} calls it oversized. "
            "tests/test_architecture.py::test_health_annotations fails any file a debt note calls oversized "
            f"that is {rule.architecture_limit} lines or fewer -- for every commit after this one, not just "
            "yours. Bringing it under the limit is the right change; take it out of its module's debt note in "
            "the same one. Mind the note's other files: a note that says 'exceeds' anywhere makes that claim "
            "about every file it names."
        ]
    return []


__all__ = [
    "ARCHITECTURE",
    "BASELINE",
    "SKIP_DIRS",
    "SizeRule",
    "debt_notes",
    "debt_recorded",
    "file_problems",
    "line_count",
    "measured",
    "read_rule",
    "stale_debt_problems",
]
