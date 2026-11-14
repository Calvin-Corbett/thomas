"""Which tests failed, read from a pytest JUnit report and named by test id.

A proof compares two runs -- one on the base, one with the change -- and the comparison is only as good as
the name it compares by. Console output is not that name: it wraps, it renumbers, and a reordered run
prints the same failures in a different order. The JUnit report gives every case a file, a class path and
a name, which together are the id pytest itself would take back on the command line, so the same test is
the same string in both runs and can be re-run on its own.

The ratchet's design asks for the same thing -- "collecting failing test ids from a JUnit report" (§3) --
so this is meant to serve its proof step too once that is built.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Report:
    """One JUnit report: every case it recorded, the ones that failed or errored, and each case's module."""

    seen: tuple[str, ...]
    failed: tuple[str, ...]
    # Dotted class paths as reported by pytest; collected_files records resolved collecting modules separately.
    modules: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    collected_files: tuple[str, ...] = ()
    # Each failed case's own words: its failure or error message and the last lines of its traceback (DETAIL_LINES).
    details: tuple[tuple[str, str], ...] = ()


# The last lines of a failure are where the assertion and the line it failed on are. Measured 2026-11-06: a send-back
# named its failing tests but never their error, so a repair agent re-ran them itself, a median of 6 times a round.
DETAIL_LINES = 25
DETAIL_CHARS = 2000


def _said(case: ElementTree.Element) -> str:
    """A failed case's message and the last :data:`DETAIL_LINES` lines of its text, at most :data:`DETAIL_CHARS`."""
    found = case.find("failure")
    if found is None:
        found = case.find("error")
    if found is None:
        return ""
    message = str(found.get("message") or "").strip()
    lines = [line.rstrip() for line in str(found.text or "").strip().splitlines()]
    tail = "\n".join(lines[-DETAIL_LINES:])
    text = f"{message}\n{tail}".strip() if message and message not in tail else tail or message
    return text[-DETAIL_CHARS:]


def _file_under(root: Path | None, dotted: str) -> str:
    """The test file a dotted class path names, found by the longest prefix that is a file under *root*."""
    if root is None or not dotted:
        return ""
    parts = dotted.split(".")
    for end in range(len(parts), 0, -1):
        candidate = "/".join(parts[:end]) + ".py"
        if (Path(root) / candidate).is_file():
            return candidate
    return ""


def test_id(case: ElementTree.Element, root: Path | None = None) -> str:
    """The id pytest would take back for *case*: ``tests/test_x.py::Class::test_y``.

    Resolve ``classname`` under *root* before falling back to ``file``: inherited methods can name their
    defining file in ``file`` while pytest collects them under a different module and class. The remainder
    of ``classname`` supplies the classes; ``name`` retains parameter ids. A collection error resolves
    its module from ``name`` instead. Without *root* or ``file``, keep the dotted identity for comparison.
    """
    name = str(case.get("name") or "")
    classname = str(case.get("classname") or "")
    file = str(case.get("file") or "").replace("\\", "/")
    # Inherited cases point ``file`` at the base method, not the collecting subclass.
    collected = _file_under(root, classname or ("" if "[" in name else name))
    if collected:
        file = collected
    if not file:
        return f"{classname}::{name}" if classname else name
    module = file[:-3].replace("/", ".") if file.endswith(".py") else ""
    if not classname and (not name or name == module):
        return file
    rest = classname[len(module) :].strip(".") if module and classname.startswith(module) else ""
    return "::".join([file, *(part for part in rest.split(".") if part), name])


def read_report(path: Path, root: Path | None = None) -> Report | None:
    """Parse a JUnit report. None when it is missing or not readable as one -- never an empty pass.

    *root* is the folder the run's ids are relative to, used to find a test's file when the report left
    it out.
    """
    try:
        tree = ElementTree.parse(str(path))
    except (OSError, ElementTree.ParseError):
        return None
    seen: list[str] = []
    failed: list[str] = []
    modules: list[str] = []
    skipped: list[str] = []
    collected_files: list[str] = []
    details: dict[str, str] = {}
    for case in tree.getroot().iter("testcase"):
        found = test_id(case, root)
        if not found:
            continue
        seen.append(found)
        file = found.split("::", 1)[0]
        collected_files.append(file if root is not None and (Path(root) / file).is_file() else "")
        modules.append(
            str(case.get("classname") or "")
            or (file.removesuffix(".py").replace("/", ".") if file.endswith(".py") else str(case.get("name") or ""))
        )
        # An <error> is a collection or fixture failure. It is a failure of the run, not an absence of one:
        # a change that stops a test file importing must never read as "nothing failed there".
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(found)
            said = _said(case)
            if said:
                details.setdefault(found, said)
        if case.find("skipped") is not None:
            skipped.append(found)
    return Report(
        tuple(seen), tuple(dict.fromkeys(failed)), tuple(modules), tuple(skipped), tuple(collected_files),
        tuple(details.items()),
    )  # fmt: skip


def without_cases(report: Report, files: Sequence[str]) -> tuple[str, ...]:
    """The named *files* *report* holds no case for, matched by the dotted module of each case's node id.

    Resolved collecting files take precedence over class-path prefixes. Without a resolved path, use the longest
    selected module prefix (``tests.test_x.TestY``). A name without ``.py`` is a folder, held by any case under it.
    """
    dotted = {rel: str(rel).replace("\\", "/").removesuffix(".py").replace("/", ".") for rel in files}
    named = [dotted[rel] for rel in dotted if str(rel).endswith(".py")]
    owners: set[str] = set()
    for index, module in enumerate(report.modules):
        collected = report.collected_files[index] if index < len(report.collected_files) else ""
        if collected:
            owners.add(collected.removesuffix(".py").replace("/", "."))
        else:
            owners.add(
                max((own for own in named if module == own or module.startswith(own + ".")), key=len, default="")
            )
    missing = []
    for rel, module in dotted.items():
        if str(rel).endswith(".py"):
            held = module in owners
        else:
            held = any(case == module or case.startswith(module + ".") for case in report.modules)
        if not held:
            missing.append(rel)
    return tuple(missing)


def unexpected_modules(report: Report, files: Sequence[str]) -> tuple[str, ...]:
    """The dotted modules *report* holds cases for that belong to none of the named *files*.

    A report the checker reads must account for only the files the checker asked the shard to run: a case whose module
    is not one of those files (nor under a named folder) is a case for a file the checker did not select, so the report
    was not the one this run produced (review B1, Finding A). Matched the same way as :func:`without_cases`.
    """
    dotted = [str(rel).replace("\\", "/").removesuffix(".py").replace("/", ".") for rel in files]
    py = [name for name, rel in zip(dotted, files) if str(rel).endswith(".py")]
    folders = [name for name, rel in zip(dotted, files) if not str(rel).endswith(".py")]
    out: list[str] = []
    for index, module in enumerate(report.modules):
        if not module:
            continue
        collected = report.collected_files[index] if index < len(report.collected_files) else ""
        resolved = collected.removesuffix(".py").replace("/", ".") if collected else module
        owned = resolved in py if collected else any(module == name or module.startswith(name + ".") for name in py)
        under = any(resolved == name or resolved.startswith(name + ".") for name in folders)
        if not owned and not under and module not in out:
            out.append(module)
    return tuple(out)


__all__ = ["Report", "read_report", "test_id", "unexpected_modules", "without_cases"]
