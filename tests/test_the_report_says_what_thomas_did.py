"""The run report has to record what Thomas actually did.

`attempts[].key_actions` is the report's account of the agent's work. Measured
across 105 agent turns it was non-empty ZERO times, while its siblings on the
same record were populated 100% of the time::

    attempt field   present   non-empty   rate
    goal                105         105   100%
    outcome             105         105   100%
    exit_state          105         105   100%
    errors              105          19    18%
    key_actions         105           0     0%

Not because nothing happened. The Call of Duty run made three `fs.write_file`
calls and three `diff.create` calls and still reported no key actions.

The cause: `_attempt_actions` matched only `fc == "tool"` with a name other than
`run`, and in the real stream every tool CALL is the engine's own `run` check.
The agent's work arrives as NAMED `tool_result` events. Across four real runs the
correspondence is exact -- unnamed results match `run` calls one-for-one, so
"named" cleanly separates the agent from the engine::

    run             tool calls    tool_result   named   unnamed
    to-do           2 (all run)             6       4         2
    habits          2 (all run)             6       4         2
    call of duty    4 (all run)            62      58         4
    study planner   2 (all run)            27      25         2

The existing unit fixture in test_run_report.py emits
`{"fc":"tool","name":"Edit"}`, a shape the engine never produces, and asserts
`"Edit"` appears -- so it passed the whole time. That is the failure this file
exists to prevent: a fixture that encodes what the code expects instead of what
production emits.

The transcripts below are copied from real runs, not invented.
"""

from __future__ import annotations

from thomas.forge.anvil.run_report import build_run_report

# The shape the engine really emits: tool CALLS are only ever `run`; the agent's
# work is named tool_results; check output is an UNNAMED tool_result.
REAL_SHAPE = "\n".join(
    [
        '{"fc":"say","text":"I will inspect the workspace, then build tasks.html."}',
        '{"fc":"tool_result","name":"code.project_structure","text":"3 entries"}',
        '{"fc":"tool_result","name":"fs.read_file","text":"tasks.html (0 bytes)"}',
        '{"fc":"tool_result","name":"fs.write_file","text":"tasks.html (7.2 kB)"}',
        '{"fc":"tool","name":"run","text":"static checks: syntax + parse + open (tasks.html)"}',
        '{"fc":"tool_result","text":"exit 0 parsed tasks.html STATIC_VERIFY_OK: 1 files checked","is_error":false}',
        '{"fc":"tool","name":"run","text":"browser smoke (tasks.html)"}',
        '{"fc":"tool_result","text":"BROWSER_SMOKE_OK: tasks.html: browser boot clean","is_error":false}',
        '{"fc":"final","text":"Built tasks.html."}',
    ]
)


def _report(transcript: str) -> dict:
    return build_run_report(
        goal="Build tasks.html - a to-do list.",
        transcript=transcript,
        changed_files=["tasks.html"],
        returncode=0,
        reason="1 file(s) changed",
    )


def _actions() -> list[str]:
    attempts = _report(REAL_SHAPE)["attempts"]
    assert attempts, "no attempts recorded at all"
    return list(attempts[0].get("key_actions") or [])


def test_key_actions_is_populated_on_a_real_shaped_run() -> None:
    actions = _actions()
    assert actions, (
        "key_actions is empty for a run that wrote a file. The report's account "
        "of what Thomas did records nothing, on every single run -- measured "
        "0 non-empty out of 105 agent turns before this was fixed."
    )


def test_it_names_the_agents_own_tools() -> None:
    joined = " ".join(_actions())
    for expected in ("fs.write_file", "code.project_structure", "fs.read_file"):
        assert expected in joined, (
            f"{expected!r} is missing from key_actions, so the report does not "
            f"say what Thomas did. Got: {_actions()!r}"
        )


def test_engine_checks_are_not_reported_as_agent_actions() -> None:
    """The engine's own checks belong in `validations`, not in `key_actions`.

    Both halves matter. Counting check output as an agent action would inflate
    the record with work Thomas did not do -- the same defect as the run that
    counted its own transcript as a file it had verified.
    """

    joined = " ".join(_actions())
    assert "run:" not in joined, f"the engine's `run` check is listed as an agent action: {_actions()!r}"
    assert "STATIC_VERIFY_OK" not in joined, (
        f"engine check OUTPUT is listed as an agent action: {_actions()!r}"
    )
    assert "BROWSER_SMOKE_OK" not in joined, (
        f"engine check OUTPUT is listed as an agent action: {_actions()!r}"
    )

    # The checks must still be recorded where they belong.
    validations = _report(REAL_SHAPE)["validations"]
    assert len(validations) == 2, f"expected both engine checks in validations, got {validations!r}"


def test_a_run_that_only_checked_reports_no_actions() -> None:
    """No invented content: a pass with no agent tool calls records none.

    Guards the opposite failure -- loosening the filter until unnamed check
    output starts counting as work.
    """

    only_checks = "\n".join(
        [
            '{"fc":"tool","name":"run","text":"static checks"}',
            '{"fc":"tool_result","text":"exit 0 parsed app.py","is_error":false}',
            '{"fc":"final","text":"Nothing to change."}',
        ]
    )
    attempts = _report(only_checks)["attempts"]
    assert attempts, "no attempts recorded"
    assert not attempts[0].get("key_actions"), (
        f"a pass that only ran engine checks invented agent actions: {attempts[0]!r}"
    )
