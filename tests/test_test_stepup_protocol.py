from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "test_stepup_protocol.py"
    spec = importlib.util.spec_from_file_location("test_stepup_protocol", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_stepup_protocol"] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def test_small_shards_cover_every_discovered_target_once() -> None:
    directory_groups, token_groups = mod.discover_test_targets()
    shards = mod.build_small_shards(directory_groups, token_groups)

    expected_targets = sorted(
        target for grouped in [*directory_groups.values(), *token_groups.values()] for target in grouped
    )
    actual_targets = sorted(target for shard in shards for target in shard.targets)

    assert actual_targets == expected_targets
    assert len(actual_targets) == len(set(actual_targets))


def test_small_shards_keep_prompt_pack_isolated() -> None:
    directory_groups, token_groups = mod.discover_test_targets()
    shards = mod.build_small_shards(directory_groups, token_groups)

    prompt_pack = next((shard for shard in shards if shard.name == "prompt-pack"), None)
    assert prompt_pack is not None
    assert prompt_pack.size > 0
    assert all(target.startswith("tests/prompt_pack/") for target in prompt_pack.targets)


def test_build_plan_defaults_to_large_stage() -> None:
    plan = mod.build_plan()
    stages = {step["stage"] for step in plan}

    assert "collect" in stages
    assert "small" in stages
    assert "large" in stages
    assert "full" not in stages


def test_build_plan_full_stage_adds_monolith() -> None:
    plan = mod.build_plan(max_stage="full")

    assert any(step["stage"] == "full" and step["label"] == "full-suite" for step in plan)


def test_run_executes_default_protocol_without_full_stage(monkeypatch) -> None:
    seen: list[tuple[str, str, bool]] = []

    def _fake_execute(step, *, repo_root, capture_output):
        _ = repo_root
        seen.append((step["stage"], step["label"], capture_output))
        return {
            "stage": step["stage"],
            "label": step["label"],
            "ok": True,
            "returncode": 0,
            "command": list(step["command"]),
            "target_count": step["target_count"],
            "timeout_seconds": step["timeout_seconds"],
            "elapsed_seconds": 0.01,
            "output_tail": "",
        }

    monkeypatch.setattr(mod, "_execute_step", _fake_execute)

    rc = mod.run(["--json"])

    assert rc == 0
    assert any(stage == "collect" for stage, _label, _capture in seen)
    assert any(stage == "small" for stage, _label, _capture in seen)
    assert any(stage == "large" for stage, _label, _capture in seen)
    assert all(stage != "full" for stage, _label, _capture in seen)
    assert all(capture is True for _stage, _label, capture in seen)
