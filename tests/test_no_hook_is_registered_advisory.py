"""A hook that cannot fail is not a gate -- unless it says why, where you look.

Found 2026-09-09: three workboard-inbox hooks in .pre-commit-config.yaml carry
``--advisory`` -- pre-commit, commit-msg and pre-push. That flag makes
``workboard_inbox.py`` print the unread messages and return 0 anyway, so the
check that makes an agent read its coordination messages before committing
stopped blocking anything, on every stage at once.

The flag is deliberate and the reasoning is sound. It lives in
scripts/forge/gates/workboard_inbox.py's module docstring: by commit time the
Bash gate has already forced the inbox read, a message arriving during a forty
second gate run cannot concern work that is already finished, and acked messages
were being reported unread because acks live in WORKBOARD.md and pre-commit
restores the working tree before the first hook runs, so the gate read HEAD's
copy of the board.

What was missing is any trace of that decision where a reader would meet it.
It landed in 03fbd810, whose commit message is entirely about the presence gate
-- grep it for "advisory" and you get nothing. Three gates stopped enforcing
inside a change about something else, and the only account of why was a
docstring nobody had to open.

So this file does not ban the flag. It requires that every use of it is named
here with a reason, and that the reason has somewhere to live in the gate
itself. Explicit debt in a list beats a flag nobody notices in a two-hundred
line YAML file.

READS EVERY LAYER, AND THAT IS THE POINT. A pre-commit config can differ in
three places at once: HEAD is the law now, the index is the law one commit from
now, and the working tree is what a reader sees. Today all three were different
for this exact file, and I reported the weakening gone while it sat staged the
whole time -- I was reading the wrong layer. Worse, a scoped commit builds a
temporary index from HEAD, so a gate running inside one reads neither the real
index nor the tree. A guard that checks a single layer can be told the truth by
that layer while another layer carries the change.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".pre-commit-config.yaml"
GATE = ROOT / "scripts" / "forge" / "gates" / "workboard_inbox.py"
COMMIT_TOOL = ROOT / "scripts" / "crew" / "brief" / "commit.py"

# HEAD is the law, the index is the next law, the tree is what a reader sees.
LAYERS = ("head", "index", "worktree")

_INBOX_REASON = (
    "The inbox gate cannot usefully block a commit: the Bash gate has already "
    "forced this agent to read its inbox before it could run anything, a message "
    "arriving during the gate run cannot concern work already finished, and an "
    "ack written to WORKBOARD.md is invisible to the gate because pre-commit "
    "restores the tree before the first hook runs. Blocking here only deadlocks "
    "two agents writing to each other. Reasoning in scripts/forge/gates/"
    "workboard_inbox.py's module docstring; flag added in 03fbd810, whose message "
    "does not mention it, which is why this list exists."
)

# hook id -> why it may run without blocking. An entry is a debt, not a pardon.
ADVISORY_BY_DESIGN: dict[str, str] = {
    "thomas-workboard-inbox-gate": _INBOX_REASON,
    "thomas-workboard-inbox-final-gate": _INBOX_REASON,
    "thomas-workboard-inbox-commit-msg-gate": _INBOX_REASON,
}


def _git_show(spec: str) -> str:
    """Contents of a path at a git layer, or empty if it is not there."""
    result = subprocess.run(
        ["git", "show", spec],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout:
        return result.stdout
    return ""


def _config_text(layer: str) -> str:
    if layer == "worktree":
        return CONFIG.read_text(encoding="utf-8") if CONFIG.exists() else ""
    if layer == "index":
        return _git_show(":.pre-commit-config.yaml")
    return _git_show("HEAD:.pre-commit-config.yaml")


def _hook_entries(layer: str) -> list[tuple[str, str]]:
    """(hook id, entry line) for every hook in the config at one layer."""
    entries: list[tuple[str, str]] = []
    current_id = ""
    for line in _config_text(layer).splitlines():
        id_match = re.match(r"\s*-\s*id:\s*(\S+)", line)
        if id_match:
            current_id = id_match.group(1)
            continue
        entry_match = re.match(r"\s*entry:\s*(.+)$", line)
        if entry_match and current_id:
            entries.append((current_id, entry_match.group(1).strip()))
    return entries


def _populated_layers() -> list[str]:
    """Layers that actually have a config. An unstaged file has no index blob."""
    return [layer for layer in LAYERS if _config_text(layer).strip()]


def test_the_config_is_readable_and_has_hooks() -> None:
    """Without this, every assertion below could pass on an empty parse.

    A guard whose parser silently returns nothing reports a clean repository
    forever. That is the exact failure mode this file exists to catch, so it
    would be a poor joke to ship it here.
    """
    populated = _populated_layers()
    assert populated, "no layer produced a pre-commit config; the reader is broken"
    for layer in populated:
        entries = _hook_entries(layer)
        assert len(entries) > 10, (
            f"only parsed {len(entries)} hook entries at layer {layer!r}; "
            "the parser is wrong, so a green result here means nothing"
        )


def test_no_hook_runs_a_gate_in_advisory_mode_without_saying_why() -> None:
    """The regression this file exists for.

    ``--advisory`` turns a gate into a printer. A hook registered that way
    reports the violation and lets the commit through, which reads as a passing
    gate to anyone not looking at the flag. That is allowed, but only on the
    record.
    """
    offenders: list[str] = []
    for layer in _populated_layers():
        offenders.extend(
            f"  [{layer}] {hook_id}: {entry}"
            for hook_id, entry in _hook_entries(layer)
            if "--advisory" in entry and hook_id not in ADVISORY_BY_DESIGN
        )
    assert not offenders, (
        "these hooks cannot fail, so they are not enforcing, and nothing records "
        "the decision:\n"
        + "\n".join(offenders)
        + "\n\nIf it is deliberate, add the hook id to ADVISORY_BY_DESIGN with the reason."
    )


def test_every_listed_exemption_is_still_a_real_hook() -> None:
    """An exemption must not outlive the thing it exempts.

    A permission for a hook that no longer exists is a permission lying around
    waiting for someone to reuse the name.
    """
    known = {hook_id for layer in _populated_layers() for hook_id, _ in _hook_entries(layer)}
    assert known, "parsed no hooks at all; see the readability test"
    stale = sorted(hook_id for hook_id in ADVISORY_BY_DESIGN if hook_id not in known)
    assert not stale, (
        "ADVISORY_BY_DESIGN exempts hooks that no longer exist: "
        + ", ".join(stale)
        + " -- delete the entries, do not leave the permission lying around"
    )


def test_every_reason_actually_reasons() -> None:
    """A one-word reason is a flag with extra steps."""
    thin = sorted(hook_id for hook_id, reason in ADVISORY_BY_DESIGN.items() if len(reason.strip()) < 80)
    assert not thin, (
        "these exemptions have a reason too short to be one: "
        + ", ".join(thin)
        + " -- say what blocking would fail to protect, and where the argument lives"
    )


def test_the_reasoning_lives_somewhere_a_reader_will_find_it() -> None:
    """The gate that can be advisory must argue for it in its own docstring.

    This is the half that was missing. The mode existed, the argument existed,
    and they never met anywhere a reader would pass through. A module docstring
    is the one place someone opening the file cannot avoid.
    """
    source = GATE.read_text(encoding="utf-8")
    if "--advisory" not in source:
        return  # no mode to explain
    docstring = ast.get_docstring(ast.parse(source)) or ""
    assert "advisory" in docstring.lower(), (
        f"{GATE.name} can be run in advisory mode but its module docstring never "
        "mentions it; the reason a gate does not block belongs where someone "
        "opening the gate will read it"
    )


def _gate_script(token: str) -> str:
    """The gate script a command token names, normalised, or empty."""
    candidate = token.strip().strip("\"'").replace("\\", "/")
    if candidate.endswith(".py") and "scripts/forge/gates/" in candidate:
        return candidate[candidate.index("scripts/forge/gates/") :]
    return ""


def _config_invocations(layer: str) -> dict[str, set[bool]]:
    """gate script -> the set of advisory-or-not it is registered with in the hooks."""
    found: dict[str, set[bool]] = {}
    for _hook_id, entry in _hook_entries(layer):
        advisory = "--advisory" in entry
        for token in entry.split():
            script = _gate_script(token)
            if script:
                found.setdefault(script, set()).add(advisory)
    return found


def _commit_tool_invocations() -> dict[str, set[bool]]:
    """gate script -> the set of advisory-or-not the commit tool invokes it with.

    Parsed with ``ast`` rather than a regex on purpose. The commit tool holds its
    gates as tuple literals, and a tuple can be reformatted across lines without
    changing meaning -- the entry this test exists for is written that way. A
    line-based reader would stop seeing the flag the moment someone ran a
    formatter, and a guard that quietly stops looking is the failure this whole
    file is about.
    """
    found: dict[str, set[bool]] = {}
    if not COMMIT_TOOL.exists():
        return found
    tree = ast.parse(COMMIT_TOOL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple):
            continue
        strings = [
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        advisory = "--advisory" in strings
        for token in strings:
            script = _gate_script(token)
            if script:
                found.setdefault(script, set()).add(advisory)
    return found


def _describe_modes(modes: set[bool]) -> str:
    return " and ".join("advisory" if mode else "blocking" for mode in sorted(modes, reverse=True))


def test_a_gate_is_registered_the_same_way_in_every_registry() -> None:
    """One gate, two registries, one answer.

    This is the miss that made the whole exercise necessary. 03fbd810 made three
    inbox hooks advisory in .pre-commit-config.yaml and left
    scripts/crew/brief/commit.py invoking the same gate with no flag at all. Both
    registrations were defensible on their own and the pair was a livelock:
    measured 2026-09-09, an agent's inbox was empty at the moment a commit began,
    a coordination message arrived during the forty second gate run, and the
    commit died -- four times running, while the hook config said that gate could
    not block anything. The gate's own docstring described the commit path as
    already advisory, so the documentation was not even wrong, it was unimplemented.

    Matching is by SCRIPT PATH, not by name. The config calls it
    thomas-workboard-inbox-gate and the commit tool calls it workboard_inbox, so
    any test keyed on the name needs a hand-written translation table, and a table
    like that goes stale silently. The script path is the one identifier both
    registries must already agree on to be running the same code at all.
    """
    tool = _commit_tool_invocations()
    if not tool:
        return  # no commit tool in this checkout; nothing to compare against
    disagreements: list[str] = []
    for layer in _populated_layers():
        config = _config_invocations(layer)
        for script, tool_modes in sorted(tool.items()):
            config_modes = config.get(script)
            if config_modes is None or config_modes == tool_modes:
                continue
            disagreements.append(
                f"  [{layer}] {script}: hooks run it {_describe_modes(config_modes)}, "
                f"{COMMIT_TOOL.name} runs it {_describe_modes(tool_modes)}"
            )
    assert not disagreements, (
        "the same gate is enforced differently depending on which registry starts it:\n"
        + "\n".join(disagreements)
        + "\n\nA gate that blocks in one path and advises in another is not a decision, "
        "it is two decisions that were never compared. Make them agree, and if the "
        "difference is deliberate, say so where both registries can be read together."
    )
