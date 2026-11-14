"""Native self-edit process binding must retain the canonical runtime boundary."""

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from thomas.forge.anvil import forge_code_runner as runner


@pytest.mark.parametrize("binding", [None, {}, {"candidate_root": "wrong", "source_root": "live"}])
def test_history_override_without_matching_private_gate_is_refused(tmp_path, monkeypatch, binding):
    monkeypatch.setenv("THOMAS_CODE_START_GATE", "pipe")
    monkeypatch.setenv("THOMAS_CODE_START_TOKEN", "private")
    payload = {"gate_token": "private", "goal": "repair", "self_edit": binding}
    gate = runner.read_start_gate(io.BytesIO(json.dumps(payload).encode()))
    with patch.object(runner, "read_start_gate", return_value=gate), patch.object(runner, "run_configured_turn") as run:
        assert (
            runner.main(
                [
                    "--project-root",
                    str(tmp_path / "candidate"),
                    "--history-root",
                    str(tmp_path / "source"),
                    "--family",
                    "gpt",
                    "--model",
                    "gpt-5.6-luna",
                ]
            )
            == 75
        )
    run.assert_not_called()


def test_bound_candidate_uses_source_history_and_private_runtime(tmp_path, monkeypatch):
    source, candidate = tmp_path / "source", tmp_path / "candidate"
    candidate.mkdir()
    gate = runner.StartGatePayload(True, "private-token", "repair", str(candidate), str(source))
    with (
        patch.object(runner, "read_start_gate", return_value=gate),
        patch.object(runner, "run_configured_turn", return_value=0) as run,
    ):
        # The environment changes belong to this child only; isolate this test's env.
        with patch.dict("os.environ", {}, clear=False):
            assert (
                runner.main(
                    [
                        "--project-root",
                        str(candidate),
                        "--history-root",
                        str(source),
                        "--family",
                        "gpt",
                        "--model",
                        "gpt-5.6-luna",
                    ]
                )
                == 0
            )
            import os

            assert Path(os.environ["THOMAS_MEMORY_DATA_DIR"]).parent == tmp_path
            assert Path(os.environ["THOMAS_MEMORY_DATA_DIR"]) not in (source, candidate)
    assert run.call_args.args[0].history_root == str(source)


def test_bound_runner_reaches_real_dispatcher_without_git(tmp_path, monkeypatch):
    from thomas.forge.anvil.dispatch_agent_loop import dispatch_via_agent_loop

    source, candidate = tmp_path / "source", tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "seed.txt").write_text("original")
    calls = []

    def model_pass(prompt, cwd, timeout, emit):
        calls.append(cwd)
        return 0, "Inspected the candidate."

    def dispatch(goal, **kwargs):
        return dispatch_via_agent_loop(goal, runner=model_pass, verify=False, **kwargs)

    from thomas.forge.anvil import agent_passes

    monkeypatch.setattr(agent_passes, "dispatch_via_agent_loop", dispatch)
    monkeypatch.setattr(
        runner,
        "read_start_gate",
        lambda: runner.StartGatePayload(True, "test-only", "inspect", str(candidate), str(source)),
    )
    monkeypatch.setattr(runner, "_default_emit", lambda event: None)
    with patch.dict("os.environ", {}, clear=False):
        runner.main(
            [
                "--project-root",
                str(candidate),
                "--history-root",
                str(source),
                "--family",
                "gpt",
                "--model",
                "gpt-5.6-luna",
            ]
        )
    assert calls == [str(candidate)]
