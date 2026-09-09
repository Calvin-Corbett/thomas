from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
STRESS = ROOT / "tests" / "stress"
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))

from chatgpt_parity_harness import (
    EvidenceRow,
    preserve_workspace_paths,
    record_delegation_runtime,
    record_model_runtime_event,
)


def _load_loop() -> ModuleType:
    spec = importlib.util.spec_from_file_location("chatgpt_parity_runtime_loop", STRESS / "chatgpt_parity_loop.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _receipt(*, model: str = "test-model", execution_id: str = "") -> dict:
    receipt = {
        "requested": {"profile": "local", "provider": "fixture", "model": "test-model"},
        "active": {"profile": "local", "provider": "fixture", "model": model},
        "failover_enabled": False,
        "failover_used": False,
        "attempts": [{"profile": "local", "provider": "fixture", "model": model, "status": "success"}],
    }
    if execution_id:
        receipt["execution_id"] = execution_id
    return receipt


def test_runtime_receipt_recording_is_secret_safe_and_fail_closed() -> None:
    context = SimpleNamespace(runtime_cache={})
    event = {
        "type": "model_runtime",
        "runtime": {
            **_receipt(),
            "active": {
                **_receipt()["active"],
                "base_url": "https://user:pass@secret.invalid/private?token=secret",
            },
            "token": "secret",
        },
    }

    assert record_model_runtime_event(context, event) is True
    assert "secret" not in json.dumps(context.runtime_cache["model_runtime_receipts"][0])
    assert record_model_runtime_event(context, {"type": "model_runtime", "runtime": {}}) is False
    assert (
        record_model_runtime_event(
            context,
            {"type": "model_runtime", "runtime": {"trace_error": "sk-secret-token"}},
        )
        is False
    )
    assert record_model_runtime_event(context, {"type": "text", "text": "ok"}) is False


def test_delegation_receipt_is_bound_to_execution_and_required() -> None:
    context = SimpleNamespace(runtime_cache={})
    valid_row = {
        "execution_id": "exec-valid",
        "runtime_profile": {"model_runtime": _receipt()},
    }
    missing_row = {"execution_id": "exec-missing", "runtime_profile": {}}

    assert record_delegation_runtime(context, valid_row) is True
    assert record_delegation_runtime(context, missing_row) is False
    stored = context.runtime_cache["model_runtime_receipts"][0]
    assert stored["execution_id"] == "exec-valid"
    assert context.runtime_cache["delegated_execution_ids"] == ["exec-valid", "exec-missing"]


@pytest.mark.parametrize(
    "receipt",
    [
        {**_receipt(), "attempts": []},
        {**_receipt(), "attempts": [{**_receipt()["attempts"][0], "status": "error"}]},
        {**_receipt(), "trace_error": "runtime_trace_failed"},
        {**_receipt(model="fallback-model"), "failover_used": True},
    ],
)
def test_runtime_attribution_rejects_unproven_or_mismatched_models(receipt: dict) -> None:
    loop = _load_loop()
    context = SimpleNamespace(runtime_cache={"model_runtime_receipts": [receipt]})

    attribution = loop._runtime_attribution(context, profile="local", model_id="test-model")

    assert attribution["status"] == "unverified"
    assert attribution["failures"]


def test_runtime_attribution_requires_every_delegated_execution_receipt() -> None:
    loop = _load_loop()
    context = SimpleNamespace(
        runtime_cache={
            "model_runtime_receipts": [_receipt(execution_id="exec-valid")],
            "delegated_execution_ids": ["exec-valid", "exec-missing"],
        }
    )

    attribution = loop._runtime_attribution(context, profile="local", model_id="test-model")

    assert attribution["status"] == "unverified"
    assert attribution["missing_delegated_execution_ids"] == ["exec-missing"]


def test_runtime_tree_hash_binds_server_and_web_source_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _load_loop()
    runtime = tmp_path / "thomas"
    web = runtime / "server" / "web"
    web.mkdir(parents=True)
    (runtime / "brain.py").write_text("VERSION = 1\n", encoding="utf-8")
    client = web / "app.mjs"
    client.write_text("export const version = 1;\n", encoding="utf-8")
    (runtime / "state.json").write_text('{"volatile": 1}\n', encoding="utf-8")
    monkeypatch.setattr(loop, "_REPO_ROOT", tmp_path)

    before = loop._runtime_tree_sha256()
    client.write_text("export const version = 2;\n", encoding="utf-8")
    after_source_change = loop._runtime_tree_sha256()
    (runtime / "state.json").write_text('{"volatile": 2}\n', encoding="utf-8")

    assert after_source_change != before
    assert loop._runtime_tree_sha256() == after_source_change


def test_workspace_guard_restores_all_paths_even_after_one_cleanup_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.txt"
    restored = tmp_path / "restored.txt"
    broken.write_bytes(b"before-broken")
    restored.write_bytes(b"before-restored")

    with pytest.raises(RuntimeError, match="probe workspace cleanup failed"):
        with preserve_workspace_paths(tmp_path, ["broken.txt", "restored.txt"]):
            broken.unlink()
            broken.mkdir()
            restored.write_bytes(b"during")

    assert restored.read_bytes() == b"before-restored"


def test_workspace_guard_restores_existing_removes_created_and_rejects_escape(tmp_path: Path) -> None:
    existing = tmp_path / "existing.txt"
    created = tmp_path / "created.txt"
    existing.write_bytes(b"before")

    with pytest.raises(RuntimeError, match="probe failed"):
        with preserve_workspace_paths(tmp_path, ["existing.txt", "created.txt"]):
            existing.write_bytes(b"during")
            created.write_bytes(b"temporary")
            raise RuntimeError("probe failed")

    assert existing.read_bytes() == b"before"
    assert not created.exists()
    with pytest.raises(ValueError, match="escapes repository"):
        with preserve_workspace_paths(tmp_path, ["../outside.txt"]):
            pass


def test_credentialed_base_url_is_never_persisted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _load_loop()
    rubric = {
        "schema_version": "thomas-chatgpt-parity-v1",
        "target": "test",
        "as_of": "2026-07-15",
        "source_urls": ["https://example.test"],
        "scoring": {str(tier): f"tier {tier}" for tier in range(5)},
        "families": [
            {
                "id": "core",
                "name": "Core",
                "weight": 1.0,
                "critical": True,
                "behaviors": ["behaves"],
                "tiers": {str(tier): [{"kind": "manual", "severity": "critical"}] for tier in range(1, 5)},
            }
        ],
    }
    rubric_path = tmp_path / "rubric.json"
    rubric_path.write_text(json.dumps(rubric), encoding="utf-8")
    args = SimpleNamespace(
        rubric=str(rubric_path),
        output_dir=str(tmp_path / "proof"),
        base_url="http://user:pass@127.0.0.1:8908/private?token=sekret#fragment",
        profile="local",
        model_id="test-model",
        run_tests=True,
        timeout_seconds=5.0,
        family=[],
        run_id="credential-redaction",
    )

    def collect(rubric_data: dict, context: object) -> list[EvidenceRow]:
        context.runtime_cache["model_runtime_receipts"] = [_receipt()]
        return [EvidenceRow("core", tier, f"core-{tier}", "pass", "pass", True, "critical") for tier in range(1, 5)]

    monkeypatch.setattr(loop, "collect_evidence", collect)
    scorecard = loop.run(args)

    assert scorecard["base_url"] == "http://127.0.0.1:8908"
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in Path(args.output_dir).rglob("*") if path.is_file()
    )
    assert "user:pass" not in serialized
    assert "token=sekret" not in serialized
    assert "/private" not in serialized
    assert "#fragment" not in serialized
    assert "http://127.0.0.1:8908" in serialized
