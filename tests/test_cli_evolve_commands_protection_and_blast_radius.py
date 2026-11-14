"""Evolve's protection: protected files, blast radius, the clean exam mirror, and architecture debt sync.

Split from test_cli_evolve_commands.py on 2026-09-07 so each file stays under the monolith guard's limit.
"""
from __future__ import annotations

import sys
from pathlib import Path

from tests._cli_evolve_fakes import _seed_repo
from thomas.forge.anvil import evolve as evolve_runtime
from thomas.forge.anvil.doppelganger import (
    get_paths,
)


def test_evolve_run_reverts_protected_file_changes(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["tests/test_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            Path(cwd, "tests", "test_architecture.py").write_text(
                "def test_smoke():\n    assert False\n", encoding="utf-8"
            )
            return {
                "command": "chat",
                "returncode": 0,
                "stdout_tail": "updated",
                "stderr_tail": "",
                "timed_out": False,
            }
        return {
            "command": "verify",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(tmp_path, goal="Safe runtime tweak")
    session = payload["session"]
    green_test = get_paths(tmp_path).green_root / "tests" / "test_architecture.py"

    assert session["status"] == "policy_violation"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["policy_violations"] == ["tests/test_architecture.py"]
    assert session["tamper_count"] == 1
    assert session["verification"] == []
    assert "protected path tamper detected before verification" in session["verification_skipped_reason"]
    assert "tests/test_architecture.py" not in session["changed_files"]
    assert "thomas/__init__.py" in session["changed_files"]
    assert green_test.read_text(encoding="utf-8") == (
        "import thomas\n\n\ndef test_smoke():\n    assert thomas.__version__\n"
    )
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_promote_rejects_whole_session_after_protected_tamper(tmp_path: Path, monkeypatch) -> None:
    """A protected-path tamper rejects the whole session, even with clean edits."""
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["tests/test_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
            Path(cwd, "tests", "test_architecture.py").write_text(
                "def test_smoke():\n    assert False\n", encoding="utf-8"
            )
            return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}
        return {"command": "verify", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(tmp_path, goal="tweak", promote_on_pass=True)
    session = payload["session"]

    assert session["status"] == "policy_violation"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["policy_violations"] == ["tests/test_architecture.py"]
    assert session["tamper_count"] == 1
    assert session["verification"] == []
    assert "protected path tamper detected before verification" in session["verification_skipped_reason"]
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'
    assert (tmp_path / "tests" / "test_architecture.py").read_text(
        encoding="utf-8"
    ) == "import thomas\n\n\ndef test_smoke():\n    assert thomas.__version__\n"


def test_evolve_run_cannot_promote_without_verification_evidence(tmp_path: Path, monkeypatch) -> None:
    """A non-Python-only change with an empty verification ladder must fail closed."""
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "README.md").write_text("unverified docs change\n", encoding="utf-8")
        return {"command": "chat", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(
        evolve_runtime,
        "_build_verify_plan",
        lambda charter, delta, repo_root, *, goal="", acceptance_checks=None: [],
    )

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Make an unverified non-Python change",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["changed_files"] == ["README.md"]
    assert session["verification"] == []
    assert session["status"] == "unverified"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert not (tmp_path / "README.md").exists()


def test_evolve_run_rejects_new_loop_package_python_file(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "forge", "anvil").mkdir(parents=True, exist_ok=True)
            Path(cwd, "thomas", "forge", "anvil", "evolve_fake_gate.py").write_text(
                "ALWAYS_PASS = True\n",
                encoding="utf-8",
            )
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.4.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Install a fake evolve gate",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert any("new evolve-loop Python file" in item for item in session["session_rejections"])
    assert not (tmp_path / "thomas" / "forge" / "anvil" / "evolve_fake_gate.py").exists()
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_allows_existing_loop_package_python_change_with_blast_radius(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas" / "forge" / "anvil").mkdir(parents=True)
    (tmp_path / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").write_text(
        "RANKER = 'blue'\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_evolve_loop_learning.py").write_text(
        "from thomas.forge.anvil import evolve_loop_learning\n\n\n"
        "def test_ranker_is_configured():\n"
        "    assert evolve_loop_learning.RANKER\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "forge", "anvil", "evolve_loop_learning.py").write_text(
                "RANKER = 'green'\n",
                encoding="utf-8",
            )
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Retune the existing evolve ranker under supervisor review",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "ready"
    assert session["promotable"] is True
    assert session["promoted"] is False
    assert session["session_rejections"] == []
    assert session["verification_floor_failures"] == []
    assert session["changed_files"] == ["thomas/forge/anvil/evolve_loop_learning.py"]
    assert (tmp_path / "thomas" / "forge" / "anvil" / "evolve_loop_learning.py").read_text(
        encoding="utf-8"
    ) == "RANKER = 'blue'\n"
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_rejects_test_infra_changes(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "tests", "conftest.py").write_text(
                "collect_ignore = ['test_architecture.py']\n", encoding="utf-8"
            )
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Suppress tests",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert any("test infrastructure changed" in item for item in session["session_rejections"])
    assert session["verification"] == []
    assert "session rejected before verification" in session["verification_skipped_reason"]
    assert not (tmp_path / "tests" / "conftest.py").exists()
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_rejects_green_support_file_tamper(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\npolicy_files=[]\nguardrails_files=[]\nenforcement_files=[]\nenforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "agent_safety.toml").write_text(
                "[protected]\n"
                "policy_files=[]\n"
                "guardrails_files=[]\n"
                "enforcement_files=[]\n"
                "enforcement_scripts=[]\n"
                "# green tamper\n",
                encoding="utf-8",
            )
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.1"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tamper with green support policy before verifying",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert any("green support file changed" in item for item in session["session_rejections"])
    assert session["verification"] == []
    assert "session rejected before verification" in session["verification_skipped_reason"]
    assert (tmp_path / "agent_safety.toml").read_text(encoding="utf-8").strip().endswith("enforcement_scripts=[]")
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_rejects_green_corpus_tamper(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "evolve_corpus", "cases", "known_good_minimal.json").write_text(
                '{"case_id":"tampered"}\n',
                encoding="utf-8",
            )
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.2"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Tamper with green corpus before verifying",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert any("green support file changed" in item for item in session["session_rejections"])
    assert session["verification"] == []
    assert "session rejected before verification" in session["verification_skipped_reason"]
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_verification_runs_in_clean_exam_mirror(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    verify_cwds: list[Path] = []

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.2"\n', encoding="utf-8")
            Path(cwd, "pytest.py").write_text("raise RuntimeError('shadowed')\n", encoding="utf-8")
        elif isinstance(command, list):
            verify_cwd = Path(cwd)
            verify_cwds.append(verify_cwd)
            assert env["PYTHONPATH"] == str(verify_cwd)
            assert not (verify_cwd / "pytest.py").exists()
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Verify in a clean exam mirror",
        promote_on_pass=False,
        refactor_first=False,
    )
    session = payload["session"]
    paths = get_paths(tmp_path)

    assert session["status"] == "ready"
    assert session["promotable"] is True
    assert verify_cwds
    assert Path(session["verification_root"]) in verify_cwds
    assert Path(session["verification_root"]).with_name("verify-blue") in verify_cwds
    assert all(path != paths.green_root for path in verify_cwds)
    assert (paths.green_root / "pytest.py").exists()
    assert not (Path(session["verification_root"]) / "pytest.py").exists()


def test_evolve_run_rejects_verification_sandbox_drift(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.2"\n', encoding="utf-8")
        elif isinstance(command, list):
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.5.3"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Let verification mutate green after delta capture",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "rejected"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert any("verification sandbox content changed" in item for item in session["session_rejections"])
    assert session["verification_sandbox_rejections"]
    assert not session["delta_drift_rejections"]
    assert session["delta"]["changed_files"] == ["thomas/__init__.py"]
    assert session["post_verification_delta"]["changed_files"] == ["thomas/__init__.py"]
    assert session["verified_delta_fingerprint"] == session["post_verification_delta_fingerprint"]
    assert session["verification_delta_fingerprint"] != session["post_verification_sandbox_fingerprint"]
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_blocks_py_compile_only_verification(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    (tmp_path / "thomas" / "core").mkdir()
    (tmp_path / "thomas" / "core" / "__init__.py").write_text("", encoding="utf-8")

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "core", "untested.py").write_text("VALUE = 1\n", encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))
    monkeypatch.setattr(
        evolve_runtime,
        "_build_verify_commands",
        lambda charter, delta, repo_root, *, goal="", acceptance_checks=None: [
            [sys.executable, "-m", "py_compile", "thomas/core/untested.py"]
        ],
    )

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Add untested module",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "verification_failed"
    assert session["verification"] == []
    assert session["verification_floor_failures"] == [
        "no blast-radius tests selected for changed Python files: thomas/core/untested.py"
    ]
    assert "verification floor failed before subprocess verification" in session["verification_skipped_reason"]
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert not (tmp_path / "thomas" / "core" / "untested.py").exists()


def test_evolve_run_blocks_import_only_blast_radius_spoof(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    feature_root = tmp_path / "thomas" / "feature"
    feature_root.mkdir()
    (feature_root / "__init__.py").write_text("", encoding="utf-8")
    (feature_root / "payments.py").write_text("def charge(x):\n    return x\n", encoding="utf-8")
    (tmp_path / "tests" / "test_payments.py").write_text(
        "from thomas.feature import payments\n\n\ndef test_import_only():\n    assert payments\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "feature", "payments.py").write_text(
                "def charge(x):\n    return x * 999\n",
                encoding="utf-8",
            )
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Change payments behind an import-only test",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "verification_failed"
    assert session["verification"] == []
    assert len(session["verification_floor_failures"]) == 1
    assert "no changed executable lines covered" in session["verification_floor_failures"][0]
    assert "thomas/feature/payments.py" in session["verification_floor_failures"][0]
    assert "verification floor failed before subprocess verification" in session["verification_skipped_reason"]
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert (tmp_path / "thomas" / "feature" / "payments.py").read_text(encoding="utf-8") == (
        "def charge(x):\n    return x\n"
    )


def test_evolve_run_blocks_rename_to_escape_blast_radius_tests(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    core_root = tmp_path / "thomas" / "core"
    core_root.mkdir()
    (core_root / "__init__.py").write_text("", encoding="utf-8")
    (core_root / "covered.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_core_covered.py").write_text(
        "from thomas.core import covered\n\n\ndef test_value():\n    assert covered.VALUE == 1\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "core", "covered.py").unlink()
            Path(cwd, "thomas", "core", "renamed.py").write_text("VALUE = 2\n", encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Rename around blast-radius tests",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "verification_failed"
    assert session["verification_floor_failures"] == [
        "no blast-radius tests selected for changed Python files: thomas/core/renamed.py"
    ]
    assert session["verification"] == []
    assert "verification floor failed before subprocess verification" in session["verification_skipped_reason"]
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert (tmp_path / "thomas" / "core" / "covered.py").exists()
    assert not (tmp_path / "thomas" / "core" / "renamed.py").exists()


def test_evolve_run_syncs_stale_architecture_debt_after_refactor(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    cli_root = tmp_path / "thomas" / "cli"
    cli_root.mkdir(parents=True)
    (cli_root / "repl.py").write_text("\n".join("x = 1" for _ in range(900)), encoding="utf-8")
    (cli_root / "still_big.py").write_text("\n".join("y = 1" for _ in range(900)), encoding="utf-8")
    (tmp_path / "thomas" / "_architecture.py").write_text(
        (
            "MODULES = {\n"
            '    "cli": {\n'
            '        "tier": "core",\n'
            '        "depends_on": [],\n'
            '        "health": "yellow",\n'
            '        "debt": "repl.py exceeds 900 lines, still_big.py exceeds 900 lines",\n'
            '        "description": "cli",\n'
            "    },\n"
            "}\n"
            'RULES = {"max_new_file_lines": 800}\n'
        ),
        encoding="utf-8",
    )
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["thomas/_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "cli", "repl.py").write_text("x = 1\n", encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Split oversized repl",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["status"] == "policy_violation"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert session["policy_violations"] == ["thomas/_architecture.py"]
    assert session["tamper_count"] == 1
    assert session["architecture_sync"]["changed_files"] == ["thomas/_architecture.py"]
    assert session["architecture_sync"]["removed"] == [{"module": "cli", "path": "repl.py"}]
    arch_text = (tmp_path / "thomas" / "_architecture.py").read_text(encoding="utf-8")
    assert "repl.py exceeds 900 lines" in arch_text
    assert "still_big.py exceeds 900 lines" in arch_text
    assert len((tmp_path / "thomas" / "cli" / "repl.py").read_text(encoding="utf-8").splitlines()) == 900


def test_evolve_run_does_not_bless_agent_architecture_edits(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    original_arch = (
        "MODULES = {\n"
        '    "cli": {\n'
        '        "tier": "core",\n'
        '        "depends_on": [],\n'
        '        "health": "yellow",\n'
        '        "debt": "repl.py exceeds 900 lines",\n'
        '        "description": "cli",\n'
        "    },\n"
        "}\n"
        'RULES = {"max_new_file_lines": 800}\n'
    )
    (tmp_path / "thomas" / "_architecture.py").write_text(original_arch, encoding="utf-8")
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["thomas/_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")
            Path(cwd, "thomas", "_architecture.py").write_text(
                original_arch.replace("repl.py exceeds 900 lines", "maliciously cleared"),
                encoding="utf-8",
            )
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Try to self-approve architecture debt removal",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["architecture_sync"]["skipped_reason"] == "architecture_already_changed"
    assert session["policy_violations"] == ["thomas/_architecture.py"]
    assert "thomas/_architecture.py" not in session["changed_files"]
    assert session["status"] == "policy_violation"
    assert session["promotable"] is False
    assert session["promoted"] is False
    assert (tmp_path / "thomas" / "_architecture.py").read_text(encoding="utf-8") == original_arch
    assert (tmp_path / "thomas" / "__init__.py").read_text(encoding="utf-8").strip() == '__version__ = "0.0.0"'


def test_evolve_run_only_syncs_debt_for_changed_files(tmp_path: Path, monkeypatch) -> None:
    _seed_repo(tmp_path)
    cli_root = tmp_path / "thomas" / "cli"
    cli_root.mkdir(parents=True)
    (cli_root / "repl.py").write_text("x = 1\n", encoding="utf-8")
    original_arch = (
        "MODULES = {\n"
        '    "cli": {\n'
        '        "tier": "core",\n'
        '        "depends_on": [],\n'
        '        "health": "yellow",\n'
        '        "debt": "repl.py exceeds 900 lines",\n'
        '        "description": "cli",\n'
        "    },\n"
        "}\n"
        'RULES = {"max_new_file_lines": 800}\n'
    )
    (tmp_path / "thomas" / "_architecture.py").write_text(original_arch, encoding="utf-8")
    (tmp_path / "agent_safety.toml").write_text(
        "[protected]\n"
        "policy_files=[]\n"
        "guardrails_files=[]\n"
        'enforcement_files=["thomas/_architecture.py"]\n'
        "enforcement_scripts=[]\n",
        encoding="utf-8",
    )

    def fake_run_exec(command, *, cwd, env, timeout_seconds):
        if isinstance(command, list) and "chat" in command:
            Path(cwd, "thomas", "__init__.py").write_text('__version__ = "0.3.0"\n', encoding="utf-8")
        return {"command": "ok", "returncode": 0, "stdout_tail": "", "stderr_tail": "", "timed_out": False}

    monkeypatch.setattr(evolve_runtime, "_run_exec", fake_run_exec)
    monkeypatch.setattr(evolve_runtime, "ensure_green_venv", lambda paths: Path(sys.executable))

    payload = evolve_runtime.run_evolve_session(
        tmp_path,
        goal="Change an unrelated runtime file",
        promote_on_pass=True,
        refactor_first=False,
    )
    session = payload["session"]

    assert session["architecture_sync"]["changed_files"] == []
    assert session["architecture_sync"]["removed"] == []
    assert session["promoted"] is True
    assert (tmp_path / "thomas" / "_architecture.py").read_text(encoding="utf-8") == original_arch
