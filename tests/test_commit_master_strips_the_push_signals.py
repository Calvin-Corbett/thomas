"""The commit tool strips the variables that make the core overhead guard treat a run as a push.

Proves scripts.forge.commit_master (sanitize_env) and scripts.forge.gates.core_overhead_guard: a commit-time gate run
never inherits the pushed-range refs or the pre-push stage signals from the worker's environment.
"""

from __future__ import annotations

import pytest
from scripts.forge.commit_master import sanitize_env


@pytest.mark.parametrize(
    "name",
    [
        "PRE_COMMIT_FROM_REF",
        "PRE_COMMIT_TO_REF",
        "PRE_COMMIT_REMOTE_NAME",
        "PRE_COMMIT_REMOTE_URL",
        "PRE_COMMIT_HOOK_STAGE",
    ],
)
def test_a_push_signal_in_the_workers_environment_does_not_reach_a_gate(name):
    out = sanitize_env({name: "x", "KEEP": "yes"})
    assert name not in out and out["KEEP"] == "yes"
