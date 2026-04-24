from __future__ import annotations

from types import SimpleNamespace

import scripts.doc as mod


def _enable_breakglass(monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-12345")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "emergency bypass for focused test harness")
    monkeypatch.setenv("AGENT_ID", "Codex Test")
    monkeypatch.setattr(
        mod,
        "authorize_breakglass",
        lambda **_: SimpleNamespace(
            ok=True,
            message="approved",
            actor="WORKSTATION\\operator",
            method="windows-credential-dialog",
            cancelled=False,
        ),
    )


def test_run_rejects_skip_overrides_without_breakglass(monkeypatch, capsys) -> None:
    called = {"count": 0}

    def _fake_run_step(_label: str, _cmd: tuple[str, ...]) -> tuple[int, float]:
        called["count"] += 1
        return 0, 0.0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_iter_steps", lambda **_: [("step", ("python", "-c", "pass"))])
    monkeypatch.delenv("THOMAS_SKIP_BREAKGLASS", raising=False)
    monkeypatch.delenv("THOMAS_SKIP_TICKET", raising=False)
    monkeypatch.delenv("THOMAS_SKIP_REASON", raising=False)
    monkeypatch.delenv("AGENT_ID", raising=False)

    rc = mod.run(["--skip-tests"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "--skip-gates/--skip-tests are breakglass-only" in out
    assert called["count"] == 0


def test_run_requires_explicit_breakglass_metadata_for_skip_flags(monkeypatch, capsys) -> None:
    called = {"count": 0}

    def _fake_run_step(_label: str, _cmd: tuple[str, ...]) -> tuple[int, float]:
        called["count"] += 1
        return 0, 0.0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_iter_steps", lambda **_: [("step", ("python", "-c", "pass"))])
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.delenv("THOMAS_SKIP_TICKET", raising=False)
    monkeypatch.delenv("THOMAS_SKIP_REASON", raising=False)
    monkeypatch.delenv("AGENT_ID", raising=False)

    rc = mod.run(["--skip-tests"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "breakglass requires THOMAS_SKIP_TICKET" in out
    assert called["count"] == 0


def test_run_allows_skip_after_human_authorization(monkeypatch) -> None:
    seen: list[str] = []

    def _fake_run_step(label: str, _cmd: tuple[str, ...]) -> tuple[int, float]:
        seen.append(label)
        return 0, 0.0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_iter_steps", lambda **_: [("step", ("python", "-c", "pass"))])
    _enable_breakglass(monkeypatch)

    rc = mod.run(["--skip-tests"])

    assert rc == 0
    assert seen == ["step"]
