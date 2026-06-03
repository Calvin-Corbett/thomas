from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import scripts.forge.gates.precommit_skip_policy as mod


def _approve_breakglass(monkeypatch, *, actor: str = "WORKSTATION\\corbe") -> None:
    monkeypatch.setattr(
        mod,
        "authorize_breakglass",
        lambda **_: SimpleNamespace(
            ok=True,
            message="approved",
            actor=actor,
            method="windows-credential-dialog",
            cancelled=False,
        ),
    )


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


def test_fails_when_breakglass_reason_missing(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-2001")
    monkeypatch.delenv("THOMAS_SKIP_REASON", raising=False)

    rc = mod.run(["--audit-log", str(audit_log)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "breakglass requires THOMAS_SKIP_REASON" in out
    assert not audit_log.exists()


def test_fails_when_skip_set_without_agent(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-release-update-gate")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Scoped commit; hook blocked by repo-wide drift.")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-2002")
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
    # Previously xfail: the old GITHUB_ACTIONS "ci-trusted" branch bypassed the
    # mocked authorize_breakglass on Linux CI, so the auth method came back
    # "ci-trusted" instead of "windows-credential-dialog". B4 removed that
    # branch, so breakglass now always routes through authorize_breakglass
    # (mocked here) and the method is deterministic on every platform.
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-release-hygiene-gate,thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Scoped commit; unrelated repo-wide gate conflict.")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-1234")
    monkeypatch.setattr(mod, "_staged_files", lambda: ["AGENTS.md", "scripts/crew/workboard/issue.py"])
    monkeypatch.setattr(mod, "_run_git", lambda _args: "mock")
    _approve_breakglass(monkeypatch)

    rc = mod.run(["--audit-log", str(audit_log), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["skip_hook_count"] == 2
    assert payload["breakglass_human_verified"] is True
    assert payload["breakglass_auth_method"] == "windows-credential-dialog"
    assert payload["breakglass_authorized_by"] == "WORKSTATION\\corbe"
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
    assert logged["staged_files"] == ["AGENTS.md", "scripts/crew/workboard/issue.py"]
    assert logged["breakglass_human_verified"] is True
    assert logged["breakglass_auth_method"] == "windows-credential-dialog"
    assert logged["breakglass_authorized_by"] == "WORKSTATION\\corbe"


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
    assert "SKIP is breakglass-only" in out
    assert not audit_log.exists()


def test_allows_protected_hook_with_breakglass_and_ticket(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-architecture")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Breakglass for temporary maintainer-approved unblock.")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-1234")
    monkeypatch.setattr(mod, "_staged_files", lambda: ["scripts/forge/gates/precommit_skip_policy.py"])
    monkeypatch.setattr(mod, "_run_git", lambda _args: "mock")
    _approve_breakglass(monkeypatch)

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


def test_fails_when_skip_hook_count_exceeds_limit_even_with_breakglass(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "a,b,c,d,e")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Too many gates for one commit.")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-2003")

    rc = mod.run(["--audit-log", str(audit_log), "--max-skip-hooks", "4"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "SKIP contains 5 hook ids; max is 4 even with THOMAS_SKIP_BREAKGLASS=1" in out
    assert not audit_log.exists()


def test_fails_when_skip_used_without_breakglass(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Need temporary bypass while investigating.")
    monkeypatch.delenv("THOMAS_SKIP_BREAKGLASS", raising=False)

    rc = mod.run(["--audit-log", str(audit_log)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "SKIP is breakglass-only" in out
    assert not audit_log.exists()


def test_fails_when_breakglass_ticket_missing(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Need temporary bypass while investigating.")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.delenv("THOMAS_SKIP_TICKET", raising=False)

    rc = mod.run(["--audit-log", str(audit_log)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "breakglass requires THOMAS_SKIP_TICKET" in out
    assert not audit_log.exists()


def test_fails_when_breakglass_staged_files_exceed_hard_limit(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Need temporary bypass while investigating baseline.")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-2004")
    monkeypatch.setattr(mod, "_staged_files", lambda: ["f1.py", "f2.py", "f3.py", "f4.py"])

    rc = mod.run(["--audit-log", str(audit_log), "--max-staged-files-with-breakglass", "3"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "breakglass SKIP with 4 staged files exceeds hard limit 3" in out
    assert not audit_log.exists()


def test_fails_when_breakglass_cooldown_active(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    now = datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc)
    # B5: history + quota now bind to the VERIFIED actor (breakglass_authorized_by),
    # not the spoofable AGENT_ID.
    audit_log.write_text(
        json.dumps(
            {
                "gate": "precommit_skip_policy",
                "timestamp_utc": "2026-02-27T11:55:00+00:00",
                "agent": "Codex 3",
                "breakglass_authorized_by": "WORKSTATION\\corbe",
                "breakglass_used": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SKIP", "thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Need temporary bypass while investigating baseline.")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-2005")
    monkeypatch.setattr(mod, "_staged_files", lambda: ["scripts/forge/gates/precommit_skip_policy.py"])
    monkeypatch.setattr(mod, "_now_utc", lambda: now)
    _approve_breakglass(monkeypatch)

    rc = mod.run(["--audit-log", str(audit_log), "--breakglass-cooldown-minutes", "15"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "breakglass cooldown active for `WORKSTATION\\corbe`" in out


def test_fails_when_breakglass_quota_exceeded(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    now = datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc)
    rows = [
        {
            "gate": "precommit_skip_policy",
            "timestamp_utc": "2026-02-27T09:00:00+00:00",
            "agent": "Codex 3",
            "breakglass_authorized_by": "WORKSTATION\\corbe",
            "breakglass_used": True,
        },
        {
            "gate": "precommit_skip_policy",
            "timestamp_utc": "2026-02-27T10:00:00+00:00",
            "agent": "Codex 3",
            "breakglass_authorized_by": "WORKSTATION\\corbe",
            "breakglass_used": True,
        },
    ]
    audit_log.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    monkeypatch.setenv("SKIP", "thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Need temporary bypass while investigating baseline.")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-2006")
    monkeypatch.setattr(mod, "_staged_files", lambda: ["scripts/forge/gates/precommit_skip_policy.py"])
    monkeypatch.setattr(mod, "_now_utc", lambda: now)
    _approve_breakglass(monkeypatch)

    rc = mod.run(
        ["--audit-log", str(audit_log), "--breakglass-cooldown-minutes", "0", "--breakglass-max-per-agent-24h", "2"]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "breakglass quota exceeded for `WORKSTATION\\corbe`" in out


def test_breakglass_quota_binds_to_verified_actor_not_agent_id_B5(tmp_path: Path, capsys, monkeypatch) -> None:
    # B5: rotating AGENT_ID must NOT reset the quota — history binds to the
    # verified OS actor returned by native-auth. Two prior breakglass rows for
    # actor WORKSTATION\corbe (written under a DIFFERENT agent id) must still
    # count against a fresh agent id when the same actor authenticates.
    audit_log = tmp_path / "skip_audit.jsonl"
    now = datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc)
    rows = [
        {
            "gate": "precommit_skip_policy",
            "timestamp_utc": "2026-02-27T09:00:00+00:00",
            "agent": "Codex Red A",
            "breakglass_authorized_by": "WORKSTATION\\corbe",
            "breakglass_used": True,
        },
        {
            "gate": "precommit_skip_policy",
            "timestamp_utc": "2026-02-27T10:00:00+00:00",
            "agent": "Codex Red A",
            "breakglass_authorized_by": "WORKSTATION\\corbe",
            "breakglass_used": True,
        },
    ]
    audit_log.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    monkeypatch.setenv("SKIP", "thomas-release-update-gate")
    monkeypatch.setenv("AGENT_ID", "Codex Red B")  # rotated id — must not help
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Rotating agent id to dodge the quota.")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-2007")
    monkeypatch.setattr(mod, "_staged_files", lambda: ["scripts/forge/gates/precommit_skip_policy.py"])
    monkeypatch.setattr(mod, "_now_utc", lambda: now)
    _approve_breakglass(monkeypatch)  # actor = WORKSTATION\corbe regardless of AGENT_ID

    rc = mod.run(
        ["--audit-log", str(audit_log), "--breakglass-cooldown-minutes", "0", "--breakglass-max-per-agent-24h", "2"]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "breakglass quota exceeded for `WORKSTATION\\corbe`" in out


@pytest.mark.xfail(
    reason="Test simulates a cancelled Windows credential dialog; on Linux CI the dialog path isn't taken so the test's assert rc==1 fails. Same root cause as the sibling test above (tracked separately).",
    strict=False,
)
def test_fails_when_human_authorization_is_cancelled(tmp_path: Path, capsys, monkeypatch) -> None:
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-architecture")
    monkeypatch.setenv("AGENT_ID", "Codex 3")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "Need temporary bypass while investigating baseline.")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-2007")
    monkeypatch.setattr(
        mod,
        "authorize_breakglass",
        lambda **_: SimpleNamespace(
            ok=False,
            message="breakglass authorization cancelled by user",
            actor=None,
            method="windows-credential-dialog",
            cancelled=True,
        ),
    )

    rc = mod.run(["--audit-log", str(audit_log), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["breakglass_human_verified"] is False
    assert payload["breakglass_cancelled"] is True
    assert not audit_log.exists()


def test_github_actions_env_does_not_shortcut_human_breakglass_B4(tmp_path: Path, capsys, monkeypatch) -> None:
    # B4 (praxis-unbypassable-2026-05-29): setting GITHUB_ACTIONS=true locally
    # must NOT grant a no-human "ci-trusted" breakglass. authorize_breakglass
    # must still be invoked, and its denial must block.
    audit_log = tmp_path / "skip_audit.jsonl"
    monkeypatch.setenv("SKIP", "thomas-architecture")
    monkeypatch.setenv("AGENT_ID", "attacker")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "spoofing CI to skip the human prompt")
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-9999")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")  # the spoof codex demonstrated
    monkeypatch.setattr(mod, "_staged_files", lambda: ["scripts/forge/gates/precommit_skip_policy.py"])
    monkeypatch.setattr(mod, "_run_git", lambda _args: "mock")

    calls = {"n": 0}

    def fake_auth(**_):
        calls["n"] += 1
        return SimpleNamespace(
            ok=False, message="human denied", actor=None, method="windows-credential-dialog", cancelled=True
        )

    monkeypatch.setattr(mod, "authorize_breakglass", fake_auth)

    rc = mod.run(["--audit-log", str(audit_log)])
    out = capsys.readouterr().out

    assert calls["n"] == 1, "authorize_breakglass must be called despite GITHUB_ACTIONS=true"
    assert rc == 1
    assert "FAIL" in out
