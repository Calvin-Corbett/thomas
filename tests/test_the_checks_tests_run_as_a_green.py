"""The check's test runs carry the green id as the cage account, as check.run's do (2026-10-27).

tests/conftest.py fails a session when the real Thomas data it watches changes during the run, unless the run carries
the green id. In the check that data is the caged server's own, written while the check's tests run, and the proof's
sandbox drops every THOMAS_* variable, the green id with it. Since 2026-10-26 a pytest exit 1 with no failed test in
its report makes the run incomplete, so long checks were held as "dev-side": 4b24de, all 16 shards, "pytest exit 1
contradicts its report". check.run already passes the id for this reason (162 passing tests failed, 2026-10-13).
"""

import pytest

from tests.test_lazy_baseline_failures_are_held_and_cleaned import pipeline, run  # noqa: F401
from thomas.core.green_place import GREEN_AGENT_ID
from thomas.server.precard import check
from thomas.server.proof import runner


@pytest.mark.parametrize(("cage", "expected"), [(True, GREEN_AGENT_ID), (False, None)])
def test_the_checks_tests_carry_the_green_id_only_as_the_cage_account(pipeline, monkeypatch, cage, expected):
    seen: list[dict[str, str]] = []

    def run_tests(work, files, **kwargs):
        seen.append(dict(kwargs.get("extra_env") or {}))
        return runner.ProofRun(True, "", (), 1, 1)

    monkeypatch.setattr(check.proofs, "run_tests", run_tests)
    monkeypatch.setattr(check.cage_account, "running_as_cage_account", lambda: cage)
    run(pipeline)
    assert seen and all(env.get("THOMAS_AGENT_ID") == expected for env in seen)
    assert all(env.get(check.CHECK_ENV) == "off" for env in seen)
