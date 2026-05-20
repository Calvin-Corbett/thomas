from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import validate_agent_changes as validate_gate
from forge.gates import exception_handler_gate as exception_gate
from forge.gates import precommit_skip_policy as skip_gate
from forge.gates import type_safety_gate as type_gate
from scripts.crew.brief.safety_config import clear_config_cache


@pytest.fixture(autouse=True)
def _clear_agent_safety_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_AGENT_SAFETY_CONFIG", raising=False)
    clear_config_cache()
    yield
    clear_config_cache()


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "agent_safety.toml"
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def test_validate_agent_changes_uses_configured_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = _write_config(
        tmp_path,
        """
        [stubs]
        placeholder_files = [\"custom/placeholder.py\"]
        build_output_files = [\"generated/bundle.js\"]

        [dead_code]
        directories = [\"legacy/\"]
        redirect_to = \"src/live.js\"
        """,
    )
    monkeypatch.setenv("THOMAS_AGENT_SAFETY_CONFIG", str(config_path))
    clear_config_cache()

    dead_ok, dead_errors = validate_gate.check_dead_code_not_edited(["legacy/part.js"])
    placeholder_ok, _ = validate_gate.check_placeholder_files_not_modified(["custom/placeholder.py"])
    stub_ok, _ = validate_gate.check_monolith_stubs_not_edited(["generated/bundle.js"])

    assert dead_ok is False
    assert placeholder_ok is False
    assert stub_ok is False
    assert "src/live.js" in "\n".join(dead_errors)


def test_skip_policy_reads_limits_and_protected_hooks_from_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_config(
        tmp_path,
        """
        [skip_policy]
        max_skip_hooks = 1
        max_staged_files_with_skip = 10
        max_staged_files_with_breakglass = 10
        breakglass_max_per_agent_24h = 3
        breakglass_cooldown_minutes = 15
        protected_hooks = [\"custom-protected-hook\"]
        """,
    )
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("THOMAS_AGENT_SAFETY_CONFIG", str(config_path))
    monkeypatch.setenv("SKIP", "custom-protected-hook")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-9999")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Scoped breakglass for config propagation test.")
    monkeypatch.setattr(skip_gate, "_staged_files", lambda: ["scripts/forge/gates/precommit_skip_policy.py"])
    monkeypatch.setattr(skip_gate, "_run_git", lambda _args: "mock")
    clear_config_cache()

    rc = skip_gate.run(["--audit-log", str(audit_log), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["protected_hooks_skipped"] == ["custom-protected-hook"]

    monkeypatch.setenv("SKIP", "hook-a,hook-b")
    rc = skip_gate.run(["--audit-log", str(audit_log), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert "max is 1" in payload["error"]


def test_type_safety_gate_uses_configured_targets_and_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_config(
        tmp_path,
        """
        [type_safety]
        enabled = true
        tool = \"mypy\"
        args = [\"--strict\"]
        enabled_files = [\"pkg/target.py\"]
        """,
    )
    monkeypatch.setenv("THOMAS_AGENT_SAFETY_CONFIG", str(config_path))
    monkeypatch.setattr(type_gate, "_staged_files", lambda: ["pkg/target.py", "pkg/ignored.py"])
    monkeypatch.setattr(type_gate.shutil, "which", lambda _name: "mypy")
    commands: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = ""

    def _fake_run(cmd: list[str], **_kwargs):
        commands.append(cmd)
        return _Proc()

    monkeypatch.setattr(type_gate.subprocess, "run", _fake_run)
    clear_config_cache()

    rc = type_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["enabled_modules"] == ["pkg/target.py"]
    assert commands == [["mypy", "--strict", "pkg/target.py"]]


def test_exception_gate_uses_exception_policy_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    logging_only = _write_config(
        tmp_path,
        """
        [exceptions]
        require_specific = true
        broad_catch_requires = [\"logging\"]
        ratchet = true
        """,
    )
    monkeypatch.setenv("THOMAS_AGENT_SAFETY_CONFIG", str(logging_only))
    clear_config_cache()
    assert (
        exception_gate._find_broad_handlers(
            'def f():\n    try:\n        x()\n    except Exception:\n        logger.exception("failed")\n'
        )
        == []
    )

    require_disabled = _write_config(
        tmp_path,
        """
        [exceptions]
        require_specific = false
        broad_catch_requires = [\"logging\", \"reraise\"]
        ratchet = false
        """,
    )
    monkeypatch.setenv("THOMAS_AGENT_SAFETY_CONFIG", str(require_disabled))
    clear_config_cache()
    assert (
        exception_gate._find_broad_handlers("def f():\n    try:\n        x()\n    except Exception:\n        pass\n")
        == []
    )


def test_exception_gate_ratchet_toggle_comes_from_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_config(
        tmp_path,
        """
        [exceptions]
        require_specific = true
        broad_catch_requires = [\"logging\", \"reraise\"]
        ratchet = false
        """,
    )
    monkeypatch.setenv("THOMAS_AGENT_SAFETY_CONFIG", str(config_path))
    monkeypatch.setattr(exception_gate, "_staged_files", lambda: ["pkg/example.py"])
    monkeypatch.setattr(
        exception_gate,
        "_staged_content",
        lambda _path: "def f():\n    try:\n        x()\n    except Exception:\n        pass\n",
    )
    monkeypatch.setattr(
        exception_gate,
        "_git_show_head",
        lambda _path: "def f():\n    try:\n        x()\n    except Exception:\n        pass\n",
    )
    clear_config_cache()

    rc = exception_gate.run(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ratchet_enabled"] is False
    assert payload["violations"] == [{"line": 4, "path": "pkg/example.py"}]
