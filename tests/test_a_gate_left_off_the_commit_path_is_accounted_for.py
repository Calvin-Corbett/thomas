"""A gate left off the commit path is accounted for, not forgotten.

tests/test_a_hook_that_does_not_run_on_the_commit_path.py requires every
commit-stage hook to run on the scoped commit path or be recorded as an exception.
This file holds the exceptions to the same standard as the rule. A hook withheld
pending repair must carry evidence and an expiry. A hook left to merge readiness
must really be registered there and must not also sit on the scoped path. And the
gate ratchet must read the module those gates are spliced in from, or a gate could
keep enforcing with nothing watching it.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.crew.brief.gate_parity import (  # noqa: E402
    COVERED_AT_MERGE_READINESS,
    HOOK_PARITY_GATES,
    HOOK_WITHHELD_PENDING_REPAIR,
)

from tests._hook_parity_readers import (  # noqa: E402
    _gate_script,
    _hook_blocks,
    _merge_readiness_scripts,
    _scoped_path_coverage,
)


def test_a_withheld_hook_is_a_commit_stage_hook() -> None:
    """Withholding is for commit-stage hooks only.

    A pre-push hook is absent from the commit path by nature and belongs in
    HOOK_ONLY_BY_DESIGN. Filing one here would dress an ordinary stage difference
    up as a defect under repair, and the two registries would stop meaning
    different things.
    """
    blocks = _hook_blocks()
    misfiled = sorted(
        hook_id for hook_id in HOOK_WITHHELD_PENDING_REPAIR if hook_id in blocks and "push" in blocks[hook_id]["stages"]
    )
    assert not misfiled, (
        "these are pre-push hooks filed as withheld: " + ", ".join(misfiled) + " -- move them to HOOK_ONLY_BY_DESIGN"
    )


def test_a_withheld_hook_carries_evidence_and_a_clock() -> None:
    """Withholding a commit-stage hook is debt, and debt has a date.

    Without an expiry, withheld pending repair becomes the permanent state of the
    hook the moment everyone stops looking at it -- which is exactly how eight
    gates went missing from this path in the first place. When the date passes
    this test fails and someone has to decide again: repair the hook and add it to
    HOOK_PARITY_GATES, or renew the entry with fresh evidence.
    """
    today = datetime.date.today()
    problems: list[str] = []
    for hook_id, entry in sorted(HOOK_WITHHELD_PENDING_REPAIR.items()):
        if len(entry.get("reason", "").strip()) < 80:
            problems.append(f"  {hook_id}: reason is too short to be one")
        if not entry.get("evidence", "").strip():
            problems.append(f"  {hook_id}: no evidence -- cite the file, line or finding")
        try:
            expires = datetime.date.fromisoformat(entry.get("expires", ""))
        except ValueError:
            problems.append(f"  {hook_id}: expires is not an ISO date")
            continue
        if expires < today:
            problems.append(
                f"  {hook_id}: withheld until {expires}, which has passed -- repair the hook "
                "and add it to HOOK_PARITY_GATES, or renew the entry with new evidence"
            )
    assert not problems, "withheld hooks out of order:\n" + "\n".join(problems)


def test_merge_readiness_coverage_is_real() -> None:
    """An entry in COVERED_AT_MERGE_READINESS must be true, not asserted.

    The hook's script has to be registered at merge readiness, and it must not also
    sit on the scoped path, which would contradict the split the entry records.
    Without both checks an entry here could quietly describe a hook that runs nowhere.
    """
    blocks = _hook_blocks()
    merge = _merge_readiness_scripts()
    scripts, _names = _scoped_path_coverage()
    problems: list[str] = []
    for hook_id, reason in sorted(COVERED_AT_MERGE_READINESS.items()):
        if len(reason.strip()) < 80:
            problems.append(f"  {hook_id}: reason is too short to be one")
        block = blocks.get(hook_id)
        if block is None:
            continue
        script = _gate_script(block["entry"])
        if not script:
            problems.append(f"  {hook_id}: runs no repo script, so merge readiness cannot cover it")
        elif script not in merge:
            problems.append(f"  {hook_id}: {script} is not registered in merge_readiness.py")
        elif script in scripts:
            problems.append(f"  {hook_id}: {script} is ALSO on the scoped path, contradicting the split")
    assert not problems, "merge-readiness coverage that is not real:\n" + "\n".join(problems)


def test_the_ratchet_reads_the_parity_registry() -> None:
    """The gate ratchet must see the gates spliced in from gate_parity.py.

    tests/test_no_gate_enforces_unwatched.py decides which gates enforce by reading
    source files for gate script paths. commit.py names these gates only through a
    star import, so a ratchet that read commit.py alone would lose sight of every one
    of them the moment its hook was removed from .pre-commit-config.yaml.
    """
    import tests.test_no_gate_enforces_unwatched as ratchet

    parity_module = ROOT / "scripts" / "crew" / "brief" / "gate_parity.py"
    assert parity_module in {Path(source) for source in ratchet._DEFAULT_SOURCES}, (
        "the gate ratchet does not read scripts/crew/brief/gate_parity.py"
    )
    seen = ratchet._enforcing_gates(sources=[parity_module])
    expected = {
        Path(str(token)).name
        for _name, command in HOOK_PARITY_GATES
        for token in command
        if str(token).endswith(".py") and "forge/gates/" in str(token).replace(chr(92), "/")
    }  # the venv shim scripts/_gate_python.py (ruff entries) is not a gate
    assert expected <= seen, f"the ratchet cannot find these parity gates: {sorted(expected - seen)}"
