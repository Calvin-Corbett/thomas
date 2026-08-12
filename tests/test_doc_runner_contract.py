from __future__ import annotations

from scripts import doc as mod

DELETED_RUNNER_PATHS = {
    "scripts/forge/gates/competitive_scope_gate.py",
    "scripts/forge/gates/reference_cli_metric_parity_gate.py",
    "tests/test_chat_controls.py",
    "tests/test_model_switching.py",
    "tests/test_reference_cli_metric_parity_gate.py",
}


def test_active_doc_runner_gate_and_test_paths_exist() -> None:
    assert mod._validate_active_runner_paths(include_gates=True, include_tests=True) == []


def test_retired_deleted_doc_runner_paths_are_documented() -> None:
    active_gate_paths = {path for _label, command in mod.GATE_COMMANDS for path in mod._iter_command_file_args(command)}
    active_test_paths = set(mod.CRITICAL_TEST_FILES)
    retired_paths = {check.path for check in mod.RETIRED_DOC_RUNNER_CHECKS}
    retired_messages = "\n".join(mod._retired_check_messages()).lower()

    assert DELETED_RUNNER_PATHS.isdisjoint(active_gate_paths | active_test_paths)
    assert retired_paths >= DELETED_RUNNER_PATHS
    for retired_path in DELETED_RUNNER_PATHS:
        assert retired_path in retired_messages
    assert "retired from docs runner" in retired_messages
    assert "use " in retired_messages


def test_doc_runner_fails_before_subprocess_when_gate_path_is_missing(monkeypatch, capsys) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        mod,
        "GATE_COMMANDS",
        (("Missing future gate", (mod.PY, "scripts/forge/gates/not_here.py")),),
    )
    monkeypatch.setattr(mod, "_run_step", lambda label, _cmd: calls.append(label) or (0, 0.0))

    rc = mod.run(["--no-record-problem-on-fail"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "FAIL active runner path contract" in out
    assert "Missing future gate: missing runner gate path `scripts/forge/gates/not_here.py`" in out
    assert calls == []
