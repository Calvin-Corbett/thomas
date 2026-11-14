"""A reactivation writes a claim the claims gate will accept.

Measured 2026-09-10, the moment a long-blocked P0 finally reactivated: the row
`reactivate.py` wrote carried only `agent`, `scope` and `task`. Those are the
three names in `REQUIRED_CLAIM_FIELDS`, which was the whole contract when that
line was written; `name`, `role` and `parent` became required later in
`REQUIRED_CLAIM_FIELDS_WITH_IDENTITY`, and this caller was never brought along.

The blast radius is what makes it worth a test. A malformed claim row does not
fail only for the agent being reactivated -- `commit.py` reports `could not
resolve active claim` and refuses, so ONE reactivation stopped every agent in
the repository from committing at all.
"""

from __future__ import annotations

from scripts.crew.tasks import reactivate
from scripts.forge.gates import workboard_claims as claims_gate

AGENT = "dev"
SCOPE = "a.py,b.py"
TASK = "T"


def _gate_reads(line: str):
    """Parse exactly as the gate does when it is enforcing identity."""
    return claims_gate._parse_claim_entry(1, line.lstrip("- "), require_identity_metadata=True)


def test_a_fresh_reactivation_row_satisfies_the_identity_contract():
    claim, err = _gate_reads(reactivate._claim_line(AGENT, SCOPE, TASK))
    assert err is None, err
    assert claim is not None
    assert claim.agent == AGENT
    assert claim.name, "a claim with no name is refused for the whole board"
    assert claim.role in claims_gate.AGENT_ROLES


def test_every_field_the_gate_requires_is_present():
    """Named field by field, so adding a tenth required field fails here rather
    than at the next reactivation."""
    line = reactivate._claim_line(AGENT, SCOPE, TASK)
    for field in claims_gate.REQUIRED_CLAIM_FIELDS_WITH_IDENTITY:
        assert f"{field}=" in line, f"reactivation row omits `{field}`"


def test_reactivation_does_not_demote_a_worker_to_solo():
    """Reactivation changes what an agent works on, never who it is.

    The identity has to be read with the GATE's parser: workboard_issue's
    returns only {agent, scope, task}, so preserving from that dict silently
    yields `role=solo; parent=none` every time and looks like it worked.
    """
    existing = f"agent={AGENT}; name=Dev Bot; role=worker; parent=thomas; scope=old.py; task=Old"
    claim, err = _gate_reads(reactivate._claim_line(AGENT, SCOPE, TASK, existing))
    assert err is None, err
    assert claim.name == "Dev Bot"
    assert claim.role == "worker"
    assert claim.parent == "thomas"


def test_the_new_scope_and_task_still_win():
    """Preserving identity must not preserve the OLD work as well."""
    existing = f"agent={AGENT}; name=Dev Bot; role=worker; parent=thomas; scope=old.py; task=Old"
    claim, err = _gate_reads(reactivate._claim_line(AGENT, SCOPE, TASK, existing))
    assert err is None, err
    assert claim.task == TASK
    assert set(claim.scopes) == {"a.py", "b.py"}


def test_an_unparseable_previous_row_falls_back_instead_of_raising():
    """A row the gate cannot read must not take the reactivation down with it;
    the point of the change is that a bad row stops blocking everyone."""
    claim, err = _gate_reads(reactivate._claim_line(AGENT, SCOPE, TASK, "this is not a claim row"))
    assert err is None, err
    assert claim.name == AGENT
    assert claim.role == "solo"
