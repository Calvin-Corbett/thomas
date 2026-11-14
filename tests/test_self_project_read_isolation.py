"""A damaged conversation must not make the project listing incomplete."""

import io
import json
from pathlib import Path

import pytest

from thomas.server.routes import self_project_listing_cache as listing
from thomas.server.routes.self_project_listing_cache import MAX_PROJECT_RECORD_BYTES, read_project_records


def _record(folder: Path, name: str) -> dict:
    project = {"id": name, "title": name, "thomas_project": {"execution_id": f"run-{name}"}}
    (folder / f"{name}.json").write_text(json.dumps(project), encoding="utf-8")
    return project


@pytest.mark.parametrize("strict", [False, True])
def test_bad_files_are_isolated_and_warnings_are_deduplicated(tmp_path, monkeypatch, strict):
    good = _record(tmp_path, "good")
    denied = tmp_path / "denied.json"
    denied.write_text("{}", encoding="utf-8")
    (tmp_path / "corrupt.json").write_text('{"thomas_project":', encoding="utf-8")
    (tmp_path / "oversized.json").write_bytes(b"x" * 257)
    assert MAX_PROJECT_RECORD_BYTES > 256
    monkeypatch.setattr(listing, "MAX_PROJECT_RECORD_BYTES", 256)
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path == denied:
            raise PermissionError("access denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    unread, warnings = [], []
    for _ in range(2):
        assert read_project_records(tmp_path, strict=strict, unread=unread, warnings=warnings) == [good]
    assert unread == []
    assert len(warnings) == 3
    for name in ("denied", "corrupt", "oversized"):
        assert sum(name in warning for warning in warnings) == 1


def test_same_record_name_in_different_projects_has_one_warning_each(tmp_path):
    warnings = []
    for name in ("first-project", "second-project"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "same.json").write_text("{", encoding="utf-8")
        for _ in range(2):
            assert read_project_records(folder, warnings=warnings) == []
    assert len(warnings) == 2
    assert sum("first-project" in warning for warning in warnings) == 1
    assert sum("second-project" in warning for warning in warnings) == 1


def test_strict_only_raises_for_folder_errors(tmp_path, monkeypatch):
    original = Path.iterdir

    def denied(path):
        if path == tmp_path:
            raise PermissionError("folder denied")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", denied)
    assert read_project_records(tmp_path) == []
    with pytest.raises(PermissionError, match="folder denied"):
        read_project_records(tmp_path, strict=True)


def test_listing_retains_small_summaries_not_conversation_payloads(tmp_path):
    for index in range(20):
        name = f"project-{index}"
        record = _record(tmp_path, name)
        record["turns"] = [
            {
                "role": "user",
                "ts": "2026-10-01T00:00:00Z",
                "text": "x" * 100_000,
                "attachments": [{"data": "y" * 100_000}],
            }
        ]
        (tmp_path / f"{name}.json").write_text(json.dumps(record), encoding="utf-8")
    records = read_project_records(tmp_path, strict=True)
    assert len(records) == 20
    assert len(json.dumps(records)) < 20_000
    assert all(len(row["turns"][0]["text"]) <= 256 for row in records)
    assert all("attachments" not in row["turns"][0] for row in records)


def test_streamed_summary_preserves_escaped_unicode(tmp_path):
    record = _record(tmp_path, "unicode")
    record["title"] = "Repair \U0001f600 and caf\u00e9"
    record["turns"] = [{"role": "user", "text": "\U0001f680"}]
    (tmp_path / "unicode.json").write_text(json.dumps(record), encoding="utf-8")
    assert read_project_records(tmp_path) == [record]


def test_large_valid_record_is_read_in_chunks(tmp_path, monkeypatch):
    record = _record(tmp_path, "large")
    record["turns"] = [{"role": "user", "text": "x" * 100_000}]
    payload = json.dumps(record).encode()
    original = Path.open
    sizes = []

    class TrackedReader(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= listing._READ_CHUNK
            sizes.append(size)
            return super().read(size)

    def open_file(path, *args, **kwargs):
        if path.name == "large.json":
            return TrackedReader(payload)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    rows = read_project_records(tmp_path)
    assert len(sizes) > 1
    assert rows[0]["turns"][0]["text"] == "x" * 256


def test_reader_never_requests_unbounded_content(tmp_path, monkeypatch):
    good = _record(tmp_path, "good")
    huge = tmp_path / "huge.json"
    huge.touch()
    original = Path.open
    sizes = []
    cap = 256
    monkeypatch.setattr(listing, "MAX_PROJECT_RECORD_BYTES", cap)

    class HugeReader(io.BytesIO):
        def read(self, size=-1):
            assert size >= 0, "unbounded read"
            sizes.append(size)
            return b"x" * size

    def open_file(path, *args, **kwargs):
        if path == huge:
            assert args == ("rb",)
            return HugeReader()
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    warnings, unread = [], []
    assert read_project_records(tmp_path, strict=True, unread=unread, warnings=warnings) == [good]
    assert sizes == [cap + 1]
    assert unread == []
    assert len(warnings) == 1 and "huge" in warnings[0]


@pytest.mark.parametrize(
    "patch",
    [
        {"thomas_project": {"execution_id": "green", "retirement": "broken"}},
        {"thomas_project": {"execution_id": "green", "repairs": 7}},
        {"turns": {"role": "assistant"}},
        {"turns": [None]},
        {"turns": [{"metadata": "broken"}]},
    ],
)
def test_malformed_project_fields_are_skipped(tmp_path, patch):
    bad = {"id": "broken", "thomas_project": {"execution_id": "green"}, **patch}
    (tmp_path / "broken.json").write_text(json.dumps(bad), encoding="utf-8")
    _record(tmp_path, "good")
    warnings = []
    assert [row["id"] for row in read_project_records(tmp_path, warnings=warnings)] == ["good"]
    assert len(warnings) == 1 and "broken" in warnings[0]


def test_listing_and_queue_keep_good_project_when_record_is_bad(tmp_path, monkeypatch):
    from thomas.server import self_project_queue_tick as queue
    from thomas.server.routes import self_project_routes as routes

    catalog = tmp_path / "catalog"
    folder = catalog / routes._CONVERSATIONS
    folder.mkdir(parents=True)
    _record(folder, "good")
    (folder / "broken.json").write_text('{"thomas_project":', encoding="utf-8")
    monkeypatch.setattr(routes, "_in_greens", lambda warnings: [])
    monkeypatch.setattr(routes.green_handoff, "sibling_changes", lambda _: {})
    monkeypatch.setattr(routes, "read_registry", lambda _catalog, _unread: {})
    monkeypatch.setattr(routes, "add_timings", lambda *args, **kwargs: {})
    monkeypatch.setattr(routes, "_handed_in", lambda conversation, *_args: {"conversation_id": conversation["id"]})

    report = routes.read_projects(catalog)
    assert report["ok"] is True
    assert report["projects"] == [{"conversation_id": "good"}]
    assert report["unreadable"] == []
    assert len(report["warnings"]) == 1 and "broken" in report["warnings"][0]
    app = {"self_project_listing_slot": {"snapshot": report}}
    assert queue._cached_listing(app) == report
    import asyncio

    from thomas.server import self_improvement_planner

    planned = []
    monkeypatch.setenv("THOMAS_OWNER_DESK", "1")
    monkeypatch.setattr(queue.autopilot_hold_tick, "port_of", lambda app: 1)
    monkeypatch.setattr(queue, "_select", lambda *a: None)
    monkeypatch.setattr(self_improvement_planner, "scan", lambda *a, **k: planned.append(True) or [])
    from thomas.server.app_keys import APP_PRAXIS_START_CODE_RUN

    app[APP_PRAXIS_START_CODE_RUN] = object()
    asyncio.run(queue.tick(app, catalog))
    assert queue._queue_conversations(catalog, {"missing"}) == {}
    assert planned == [True]
