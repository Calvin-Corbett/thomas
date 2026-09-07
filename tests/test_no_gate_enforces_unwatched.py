"""No gate may join the enforcing set without a red-path selftest.

The enforcing set = every gates/*.py named in .pre-commit-config.yaml plus
commit.py's LOCAL_GATE_COMMANDS. Gates without a RED_PATH_CASES entry must be
listed in gate_selftest_baseline.json (the debt list). The baseline may only
shrink: an entry that gains coverage must be deleted, and a NEW enforcing gate
may never be added to it. That is the ratchet.

ratchet_violations() is a pure three-way set comparison, extracted so its
three failure branches (a new uncovered+unbaselined gate, a stale baseline
entry that now has coverage, a ghost baseline entry for a gate that no longer
enforces) can each be proven to fire on synthetic input -- not just observed
never firing on the live repo state."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_name("gate_selftest_baseline.json")
_DEFAULT_SOURCES = (
    REPO_ROOT / ".pre-commit-config.yaml",
    REPO_ROOT / "scripts" / "crew" / "brief" / "commit.py",
    REPO_ROOT / ".github" / "workflows" / "gates.yml",
    REPO_ROOT / ".github" / "workflows" / "robustness-gates.yml",
    REPO_ROOT / "scripts" / "crew" / "land_checks.py",
    REPO_ROOT / "scripts" / "auto_checks.py",
    REPO_ROOT / "scripts" / "forge" / "publish" / "preflight.py",
)
_DEFAULT_GATES_DIR = REPO_ROOT / "scripts" / "forge" / "gates"


def _enforcing_gates(
    sources: Iterable[Path] | None = None,
    gates_dir: Path | None = None,
) -> set[str]:
    """Every scripts/forge/gates/*.py path named in `sources`, filtered to
    names that actually exist under `gates_dir`.

    The filter matters: a source can mention an example, a removed gate, or
    a typo'd path without that name being a real enforcing gate -- an
    unfiltered match would wrongly demand a red-path selftest (or a baseline
    entry) for a gate that does not exist. `sources`/`gates_dir` default to
    the real repo but are overridable so this can be proven on synthetic
    input, not just observed never firing on the live repo state."""
    if sources is None:
        sources = _DEFAULT_SOURCES
    if gates_dir is None:
        gates_dir = _DEFAULT_GATES_DIR
    names: set[str] = set()
    pat = re.compile(r"scripts[/\\]forge[/\\]gates[/\\]([A-Za-z0-9_]+\.py)")
    for source in sources:
        names.update(pat.findall(source.read_text(encoding="utf-8")))
    return {name for name in names if (gates_dir / name).exists()}


def ratchet_violations(enforcing: set[str], covered: set[str], baseline: set[str]) -> dict[str, set[str]]:
    """The three ways the ratchet can be violated, as pure set arithmetic.

    - new_unwatched: enforcing gates with neither coverage nor a baseline entry.
    - stale: baseline entries that now have coverage (must be deleted -- the
      ratchet only turns one way).
    - ghosts: baseline entries for gates that no longer enforce at all.
    """
    uncovered = enforcing - covered
    return {
        "new_unwatched": uncovered - baseline,
        "stale": baseline & covered,
        "ghosts": baseline - enforcing,
    }


def test_every_enforcing_gate_is_covered_or_explicitly_in_debt():
    from tests.test_every_enforcing_gate_can_fail import RED_PATH_CASES

    enforcing = _enforcing_gates()
    covered = set(RED_PATH_CASES)
    baseline = set(json.loads(BASELINE.read_text(encoding="utf-8")))
    violations = ratchet_violations(enforcing, covered, baseline)

    new_unwatched = violations["new_unwatched"]
    assert not new_unwatched, (
        f"enforcing gates with no red-path selftest and no baseline entry: "
        f"{sorted(new_unwatched)} -- write the selftest or it does not enforce"
    )
    stale = violations["stale"]
    assert not stale, (
        f"baseline entries that now have coverage -- delete them (the ratchet only turns one way): {sorted(stale)}"
    )
    ghosts = violations["ghosts"]
    assert not ghosts, f"baseline lists gates that no longer enforce: {sorted(ghosts)}"


def test_ratchet_violations_fires_new_unwatched_for_an_uncovered_ungrandfathered_gate():
    violations = ratchet_violations(enforcing={"a.py", "b.py"}, covered={"a.py"}, baseline=set())
    assert violations["new_unwatched"] == {"b.py"}
    assert violations["stale"] == set()
    assert violations["ghosts"] == set()


def test_ratchet_violations_fires_stale_for_a_baseline_entry_that_gained_coverage():
    violations = ratchet_violations(enforcing={"a.py"}, covered={"a.py"}, baseline={"a.py"})
    assert violations["stale"] == {"a.py"}
    assert violations["new_unwatched"] == set()
    assert violations["ghosts"] == set()


def test_ratchet_violations_fires_ghosts_for_a_baseline_entry_that_no_longer_enforces():
    violations = ratchet_violations(enforcing=set(), covered=set(), baseline={"z.py"})
    assert violations["ghosts"] == {"z.py"}
    assert violations["new_unwatched"] == set()
    assert violations["stale"] == set()


def test_enforcing_gates_filters_out_a_scanned_name_with_no_file_on_disk(tmp_path):
    """A source can mention scripts/forge/gates/<name>.py as an example, a
    removed gate, or a typo without that name being a real enforcing gate.
    _enforcing_gates() must filter to names that exist on disk, or the
    ratchet demands a red-path selftest / baseline entry for a gate that was
    never real (M2)."""
    fake_source = tmp_path / "fake_workflow.yml"
    fake_source.write_text(
        "run: python scripts/forge/gates/real_gate.py\nexample: python scripts/forge/gates/does_not_exist_gate.py\n",
        encoding="utf-8",
    )
    gates_dir = tmp_path / "gates"
    gates_dir.mkdir()
    (gates_dir / "real_gate.py").write_text("", encoding="utf-8")

    names = _enforcing_gates(sources=[fake_source], gates_dir=gates_dir)

    assert names == {"real_gate.py"}
