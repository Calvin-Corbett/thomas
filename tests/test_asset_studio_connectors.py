from __future__ import annotations

from thomas.marketplace.asset_studio.contracts import default_connector_catalog


def test_default_catalog_includes_new_engine_and_api_connectors() -> None:
    catalog = default_connector_catalog()
    ids = {item.id for item in catalog.list()}
    assert "unity" in ids
    assert "godot" in ids
    assert "github" in ids
    assert "notion" in ids
    assert "figma" in ids
    assert "comfyui" in ids
    assert "opentimelineio" in ids


def test_github_connector_exposes_issue_and_pr_actions() -> None:
    catalog = default_connector_catalog()
    connector = catalog.get("github")
    assert connector is not None
    action_ids = {action.id for action in connector.actions}
    assert "issue_to_task" in action_ids
    assert "pr_risk_scan" in action_ids


def test_notion_and_figma_connectors_are_python_shim_backed() -> None:
    catalog = default_connector_catalog()
    notion = catalog.get("notion")
    figma = catalog.get("figma")
    assert notion is not None
    assert figma is not None
    assert "python" in notion.executables or "python.exe" in notion.executables
    assert "python" in figma.executables or "python.exe" in figma.executables


def test_comfyui_connector_exposes_queue_and_history_actions() -> None:
    catalog = default_connector_catalog()
    connector = catalog.get("comfyui")
    assert connector is not None
    action_ids = {action.id for action in connector.actions}
    assert "queue_prompt" in action_ids
    assert "get_history" in action_ids


def test_opentimelineio_connector_exposes_validate_action() -> None:
    catalog = default_connector_catalog()
    connector = catalog.get("opentimelineio")
    assert connector is not None
    action_ids = {action.id for action in connector.actions}
    assert "validate_timeline" in action_ids
