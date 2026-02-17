from pathlib import Path

from thomas.observability import run_store


def _seed_runs() -> tuple[str, str]:
    run_ok = run_store.create_run(
        {
            "session_id": "s1",
            "profile": "local",
            "model_id": "m1",
            "mode": "auto",
            "started_at": "2026-02-10T00:00:00+00:00",
            "thomas_version": "test",
        }
    )
    run_store.append_event(
        run_ok,
        "text",
        {"type": "text", "text": "deploy green lane"},
        t_ms=0,
        seq=0,
    )
    run_store.finalize_run(
        run_ok,
        ok=True,
        error=None,
        iterations=1,
        tool_calls=0,
        usage={"tokens": 10},
    )

    run_fail = run_store.create_run(
        {
            "session_id": "s2",
            "profile": "cloud",
            "model_id": "m2",
            "mode": "thinking",
            "started_at": "2026-02-10T00:01:00+00:00",
            "thomas_version": "test",
        }
    )
    run_store.append_event(
        run_fail,
        "text",
        {"type": "text", "text": "rollback production now"},
        t_ms=0,
        seq=0,
    )
    run_store.finalize_run(
        run_fail,
        ok=False,
        error="boom",
        iterations=2,
        tool_calls=1,
        usage={"tokens": 20},
    )

    return run_ok, run_fail


def test_list_runs_filters_profile_mode_ok(tmp_path: Path):
    run_store.init_db(tmp_path / "runs.sqlite3")
    run_ok, run_fail = _seed_runs()

    out = run_store.list_runs(
        limit=20,
        offset=0,
        filters={"profile": "local", "mode": "auto", "ok": "true"},
    )
    assert [r["run_id"] for r in out] == [run_ok]

    out_fail = run_store.list_runs(
        limit=20,
        offset=0,
        filters={"ok": "false"},
    )
    ids = {r["run_id"] for r in out_fail}
    assert run_fail in ids
    assert run_ok not in ids


def test_list_runs_filters_q_search(tmp_path: Path):
    run_store.init_db(tmp_path / "runs.sqlite3")
    run_ok, run_fail = _seed_runs()

    out = run_store.list_runs(
        limit=20,
        offset=0,
        filters={"q": "rollback"},
    )
    ids = {r["run_id"] for r in out}
    assert run_fail in ids
    assert run_ok not in ids
