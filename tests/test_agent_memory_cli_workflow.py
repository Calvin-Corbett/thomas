from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_memory.cli import (
    cmd_compact,
    cmd_eval,
    cmd_init,
    cmd_lex,
    cmd_log,
    cmd_nightly,
    cmd_pin,
    cmd_query,
    cmd_train,
)


def _args(**kwargs):
    return SimpleNamespace(**kwargs)


@pytest.fixture
def memory_root(tmp_path: Path) -> Path:
    return tmp_path / "agent-memory-cli"


def test_cli_init_creates_runtime_layout(memory_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cmd_init(_args(root=str(memory_root)))
    out = capsys.readouterr().out.strip()

    assert out == "ok"
    assert (memory_root / "data").exists()
    assert (memory_root / "blobs").exists()
    assert (memory_root / "indices").exists()
    assert (memory_root / "indices" / "builds").exists()
    assert (memory_root / "indices" / "delta").exists()


def test_cli_log_and_query_json_roundtrip(memory_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cmd_init(_args(root=str(memory_root)))
    _ = capsys.readouterr()

    cmd_log(
        _args(
            root=str(memory_root),
            thread="workflow",
            etype="note",
            text="Workflow owner is Sam and rollout budget is 2",
        )
    )
    logged = capsys.readouterr().out.strip()
    assert int(logged) > 0

    cmd_query(
        _args(
            root=str(memory_root),
            thread="workflow",
            mode="deep",
            text="who owns the workflow",
            json=True,
        )
    )
    payload = json.loads(capsys.readouterr().out)
    assert "sam" in str(payload.get("packed") or "").lower()
    assert ((payload.get("trace") or {}).get("mode") or "") == "deep"


def test_cli_pin_and_lexicon_roundtrip(memory_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cmd_init(_args(root=str(memory_root)))
    _ = capsys.readouterr()

    cmd_pin(
        _args(
            root=str(memory_root),
            action="add",
            key="handoff",
            text="Continue execution after user says ok",
        )
    )
    _ = capsys.readouterr()
    cmd_pin(_args(root=str(memory_root), action="ls", key=None, text=None))
    pins_out = capsys.readouterr().out.lower()
    assert "handoff" in pins_out
    assert "continue execution after user says ok" in pins_out

    cmd_lex(
        _args(
            root=str(memory_root),
            action="add",
            phrase="SREX",
            meaning="site reliability excellence",
        )
    )
    _ = capsys.readouterr()
    cmd_lex(_args(root=str(memory_root), action="ls", phrase=None, meaning=None))
    lex_out = capsys.readouterr().out.lower()
    assert "srex" in lex_out
    assert "site reliability excellence" in lex_out


def test_cli_nightly_and_compact_keep_memory_retrievable(memory_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cmd_init(_args(root=str(memory_root)))
    _ = capsys.readouterr()

    cmd_log(
        _args(
            root=str(memory_root),
            thread="rollup",
            etype="note",
            text="handoff token is kiwi-77",
        )
    )
    _ = capsys.readouterr()

    cmd_nightly(_args(root=str(memory_root)))
    nightly_out = capsys.readouterr().out.strip()
    assert nightly_out.startswith("build_")

    cmd_compact(_args(root=str(memory_root)))
    compact_out = capsys.readouterr().out.strip()
    assert compact_out == "ok"

    cmd_query(
        _args(
            root=str(memory_root),
            thread="rollup",
            mode="deep",
            text="what is the handoff token",
            json=False,
        )
    )
    packed = capsys.readouterr().out.lower()
    assert "kiwi-77" in packed


def test_cli_eval_reports_all_pass(memory_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cmd_eval(_args(root=str(memory_root)))
    out = capsys.readouterr().out

    assert "ALL_PASS" in out
    assert "needle:" in out
    assert "temporal_contradiction:" in out
    assert "mode_stability:" in out
    assert "latency_smoke:" in out


def test_cli_query_no_memory_mode_excludes_logged_secret(memory_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cmd_init(_args(root=str(memory_root)))
    _ = capsys.readouterr()
    cmd_log(
        _args(
            root=str(memory_root),
            thread="privacy",
            etype="note",
            text="secret token is ORANGE-DELTA",
        )
    )
    _ = capsys.readouterr()

    cmd_query(
        _args(
            root=str(memory_root),
            thread="privacy",
            mode="no_memory",
            text="what is my secret token",
            json=False,
        )
    )
    packed = capsys.readouterr().out.lower()
    assert "mode: no_memory" in packed
    assert "orange-delta" not in packed


def test_cli_train_missing_optional_deps_fails_cleanly(memory_root: Path) -> None:
    if importlib.util.find_spec("sklearn") is not None:
        pytest.skip("This guardrail targets environments without optional train deps.")

    with pytest.raises(RuntimeError, match="optional dependencies"):
        cmd_train(_args(root=str(memory_root), max_traces=25))


def test_cli_pin_add_requires_key_and_text(memory_root: Path) -> None:
    with pytest.raises(ValueError, match="--key"):
        cmd_pin(_args(root=str(memory_root), action="add", key=None, text="x"))
    with pytest.raises(ValueError, match="--text"):
        cmd_pin(_args(root=str(memory_root), action="add", key="handoff", text=""))


def test_cli_pin_rm_requires_key(memory_root: Path) -> None:
    with pytest.raises(ValueError, match="--key"):
        cmd_pin(_args(root=str(memory_root), action="rm", key="", text=None))


def test_cli_lex_add_requires_phrase_and_meaning(memory_root: Path) -> None:
    with pytest.raises(ValueError, match="--phrase"):
        cmd_lex(_args(root=str(memory_root), action="add", phrase=None, meaning="expanded phrase"))
    with pytest.raises(ValueError, match="--meaning"):
        cmd_lex(_args(root=str(memory_root), action="add", phrase="SREX", meaning=None))
