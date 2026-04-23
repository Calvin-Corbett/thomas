from pathlib import Path

from thomas.demo.agentic_benchmark import load_agentic_task_pack

ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "demo" / "task_pack.agentic.product_capability_50.json"
SMOKE_PACK_PATH = ROOT / "benchmarks" / "packs" / "capability" / "thomas_product_capability_smoke10_v1.json"


def test_product_capability_pack_loads_with_50_tasks():
    pack = load_agentic_task_pack(PACK_PATH)
    tasks = list(pack.get("tasks") or [])
    ids = {str(task.get("id") or "") for task in tasks}

    assert len(tasks) == 50
    assert len(ids) == 50
    assert "web_openclaw_headline_txt" in ids
    assert "desktop_note_write_report_txt" in ids
    assert "skill_manifest_script_py" in ids
    assert "task_dispatch_visibility_report_md" in ids


def test_canonical_smoke_pack_requires_tool_using_agent_lane():
    pack = load_agentic_task_pack(SMOKE_PACK_PATH)
    tasks = list(pack.get("tasks") or [])

    assert pack["type"] == "capability"
    assert pack["family"] == "thomas_product_capability"
    assert pack["competitor_requirements"]["required_capability_class"] == "tool_using_agent"
    assert len(tasks) == 10
    assert tasks[0]["id"] == "config_default_model_json"
