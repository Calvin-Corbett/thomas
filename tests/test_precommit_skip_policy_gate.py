from __future__ import annotations

import json
from pathlib import Path

import scripts.check_precommit_skip_policy as mod


def test_passes_when_skip_not_set(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.delenv("SKIP", raising=False)
    monkeypatch.delenv("THOMAS_SKIP_REASON", raising=False)

    rc = mod.run(["--audit-log", str(audit_log)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Pre-commit skip policy gate: PASS" in out
    assert "no SKIP overrides detected" in out
    assert not audit_log.exists()


def test_fails_when_skip_set_without_reason(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.delenv("THOMAS_SKIP_REASON", raising=False)

    rc = mod.run(["--audit-log", str(audit_log)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "THOMAS_SKIP_REASON is required" in out
    assert not audit_log.exists()


def test_fails_when_skip_set_without_agent(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-release-update-gate")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Scoped commit; hook blocked by repo-wide drift.")
    monkeypatch.delenv("AGENT_ID", raising=False)
    monkeypatch.delenv("THOMAS_AGENT_ID", raising=False)
    monkeypatch.delenv("THOMAS_AGENT_NAME", raising=False)
    monkeypatch.delenv("CODEX_AGENT_NAME", raising=False)
    monkeypatch.delenv("AGENT_NAME", raising=False)
    monkeypatch.setattr(mod, "_resolve_agent", lambda: None)

    rc = mod.run(["--audit-log", str(audit_log)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "agent id is required when SKIP is set" in out
    assert not audit_log.exists()


def test_fails_for_broad_skip_tokens(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "*,thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Scoped commit; hook blocked by repo-wide drift.")

    rc = mod.run(["--audit-log", str(audit_log)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "broad SKIP tokens are not allowed" in out
    assert not audit_log.exists()


def test_records_audit_log_on_valid_skip(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-release-hygiene-gate,thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Scoped commit; unrelated repo-wide gate conflict.")
    monkeypatch.setattr(mod, "_staged_files", lambda: ["AGENTS.md", "scripts/workboard_issue.py"])
    monkeypatch.setattr(mod, "_run_git", lambda _args: "mock")

    rc = mod.run(["--audit-log", str(audit_log), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["skip_hook_count"] == 2
    assert audit_log.exists()
    rows = [line for line in audit_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    logged = json.loads(rows[0])
    assert logged["agent"] == "Codex 3"
    assert logged["skip_hooks"] == [
        "thomas-release-hygiene-gate",
        "thomas-release-update-gate",
    ]
    assert logged["reason"] == "Scoped commit; unrelated repo-wide gate conflict."
    assert logged["staged_files"] == ["AGENTS.md", "scripts/workboard_issue.py"]


def test_fails_when_protected_hook_skipped_without_breakglass(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-architecture")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Need urgent bypass due to infra issue.")
    monkeypatch.delenv("THOMAS_SKIP_BREAKGLASS", raising=False)
    monkeypatch.delenv("THOMAS_SKIP_TICKET", raising=False)

    rc = mod.run(["--audit-log", str(audit_log)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "protected hooks cannot be skipped without breakglass" in out
    assert not audit_log.exists()


def test_allows_protected_hook_with_breakglass_and_ticket(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-architecture")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Breakglass for temporary maintainer-approved unblock.")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-1234")
    monkeypatch.setattr(mod, "_staged_files", lambda: ["scripts/check_precommit_skip_policy.py"])
    monkeypatch.setattr(mod, "_run_git", lambda _args: "mock")

    rc = mod.run(["--audit-log", str(audit_log), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["breakglass_used"] is True
    assert payload["protected_hooks_skipped"] == ["thomas-architecture"]
    rows = [line for line in audit_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    logged = json.loads(rows[0])
    assert logged["breakglass_used"] is True
    assert logged["skip_ticket"] == "OPS-1234"


def test_fails_when_skip_hook_count_exceeds_limit_without_breakglass(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "a,b,c,d,e")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Too many gates for one commit.")
    monkeypatch.delenv("THOMAS_SKIP_BREAKGLASS", raising=False)

    rc = mod.run(["--audit-log", str(audit_log), "--max-skip-hooks", "4"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "SKIP contains 5 hook ids" in out
    assert not audit_log.exists()


def test_fails_when_skip_used_on_too_many_staged_files_without_breakglass(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Need temporary bypass while investigating.")
    monkeypatch.delenv("THOMAS_SKIP_BREAKGLASS", raising=False)
    monkeypatch.setattr(mod, "_staged_files", lambda: [f"file_{i}.py" for i in range(300)])

    rc = mod.run(["--audit-log", str(audit_log), "--max-staged-files-with-skip", "200"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "SKIP with 300 staged files exceeds limit 200" in out
    assert not audit_log.exists()
