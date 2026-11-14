"""What a proof found, and whether the candidate holds.

A result is read from pytest's JUnit report (xunit1). Tests are matched by node
id: at d513ccf2, 50 test names are defined in more than one test file, and
``test_cli_json_success`` in 48, so a bare name says little about which test it
is. A test whose file the candidate deleted may have moved (fcb5f06 split a
1,647-line test file), so it alone is matched by bare name, and only against the
tests in files the candidate changed.

A failure counts as dev's own only when it fails again when run alone on dev
(``confirmed``). A failure the candidate brings that passes when run alone still
blocks: order-dependent tests are not proven safe.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from thomas.server.ratchet import proof_set


@dataclass(frozen=True)
class SideResult:
    files: tuple[str, ...]
    failing: Mapping[str, str] = field(default_factory=dict)  # node id -> bare name
    passing: Mapping[str, str] = field(default_factory=dict)  # node id -> bare name, every test that passed
    ran: int = 0
    unrunnable: tuple[str, ...] = ()
    skipped: frozenset[str] = frozenset()  # node ids pytest skipped or xfailed
    confirmed: frozenset[str] | None = None  # failing node ids that failed again alone; None: not checked

    def known_failing(self) -> set[str]:
        """The failures that count as dev's own: those that failed again alone, when that was checked."""
        return set(self.failing if self.confirmed is None else self.confirmed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "files": list(self.files),
            "failing": dict(self.failing),
            "passing": dict(self.passing),
            "ran": self.ran,
            "unrunnable": list(self.unrunnable),
            "skipped": sorted(self.skipped),
            "confirmed": None if self.confirmed is None else sorted(self.confirmed),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SideResult:
        confirmed = data.get("confirmed")
        return cls(
            tuple(data.get("files") or ()),
            dict(data.get("failing") or {}),
            dict(data.get("passing") or {}),
            int(data.get("ran") or 0),
            tuple(data.get("unrunnable") or ()),
            frozenset(data.get("skipped") or ()),
            None if confirmed is None else frozenset(confirmed),
        )


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str
    new_failures: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    flaky: tuple[str, ...] = ()
    base_failing: int = 0
    with_failing: int = 0
    files: int = 0
    left_out: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _node(case: ET.Element) -> tuple[str, str]:
    file = (case.get("file") or "").replace("\\", "/")
    classname, name = case.get("classname") or "", case.get("name") or ""
    if not classname:  # a collection error: pytest names the module, and the file is the test
        return file or name, f"<collection> {file or name}"
    module = file[:-3].replace("/", ".") if file.endswith(".py") else ""
    inner = classname[len(module) + 1 :] if module and classname.startswith(module + ".") else ""
    bare = f"{inner}::{name}" if inner else name
    return (f"{file}::{bare}" if file else f"{classname}::{name}"), bare


def parse_junit(text: str) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """(failing, passing, skipped) from a pytest JUnit report (xunit1).

    The first two map node id to bare name; skipped holds node ids. pytest writes a
    skip and an xfail alike as ``<skipped>`` (``_pytest/junitxml.py:229-249``), and
    neither is a pass. The report is written while the candidate's own code runs,
    so it is untrusted input. pytest never writes a DOCTYPE; a report that declares
    one, or an entity, is refused before parsing, so no entity is ever expanded.
    (defusedxml is only a transitive dependency here, not a declared one, and
    pyproject.toml is protected.)
    """
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ET.ParseError("the report declares a DOCTYPE or an entity, which pytest never writes")
    failing: dict[str, str] = {}
    passing: dict[str, str] = {}
    skipped: set[str] = set()
    for case in ET.fromstring(text).iter("testcase"):
        key, bare = _node(case)
        if case.find("failure") is not None or case.find("error") is not None:
            failing[key] = bare
        elif case.find("skipped") is not None:
            skipped.add(key)
        else:
            passing[key] = bare
    return failing, passing, skipped


def _file(node: str) -> str:
    return node.split("::", 1)[0]


def capped(left_out: int) -> str:
    """Why a proof set past the cap does not hold: *left_out* test files that prove the change were not run."""
    return f"{left_out} test file(s) that prove it were not run: the proof set is capped at {proof_set.MAX_FILES}"


def compare(
    base: SideResult,
    cand: SideResult,
    *,
    changed: Collection[str] = (),
    flaky: Collection[str] = (),
    left_out: int = 0,
) -> Verdict:
    """Holds when nothing fails with the candidate that dev reliably fails without it, and no test is gone."""
    counts = {
        "base_failing": len(base.failing),
        "with_failing": len(cand.failing),
        "files": len(cand.files),
        "left_out": left_out,
    }
    if base.unrunnable:
        return Verdict(False, "the proof could not run on dev itself: " + base.unrunnable[0], **counts)
    if cand.unrunnable:
        return Verdict(False, "the proof could not run with the candidate: " + cand.unrunnable[0], **counts)
    if cand.ran == 0:
        return Verdict(False, "the proof ran no tests", **counts)
    if left_out:
        return Verdict(False, capped(left_out), **counts)
    changed_files, gone = set(changed), set(base.files) - set(cand.files)
    known = base.known_failing()
    known_moved = {base.failing[n] for n in known if _file(n) in gone}
    seen_in_cand = (*cand.failing.items(), *cand.passing.items())
    moved_into = {bare for node, bare in seen_in_cand if _file(node) in changed_files}
    new = tuple(
        sorted(
            node
            for node, bare in cand.failing.items()
            if node not in known and not (bare in known_moved and _file(node) in changed_files)
        )
    )
    seen = set(cand.failing) | set(cand.passing)
    missing = tuple(
        sorted(
            node
            for node, bare in base.passing.items()
            if node not in seen and not (_file(node) in gone and bare in moved_into)
        )
    )
    alone = tuple(n for n in new if n in flaky)
    if not new and not missing:
        return Verdict(True, "no test fails with it that dev does not already fail, and none is gone", **counts)
    parts = []
    if new:
        text = f"{len(new)} new failure(s): " + ", ".join(new[:5])
        if alone:
            text += f" ({len(alone)} of them pass when run alone: order-dependent, so not proven safe)"
        parts.append(text)
    if missing:
        parts.append(f"{len(missing)} test(s) that pass on dev are gone or skipped: " + ", ".join(missing[:5]))
    return Verdict(False, "; ".join(parts), new, missing, alone, **counts)


__all__ = ["SideResult", "Verdict", "capped", "compare", "parse_junit"]
