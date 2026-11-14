"""Build restrictions are actionable before execution; retries use current controls."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from tests.test_evolve_agent_routes import _drive, _new_repo
from thomas.server.routes import evolve_agent_routes as routes


@pytest.mark.parametrize(
    "autonomy,access,controls",
    [
        (1, "project", ["autonomy_level"]),
        (2, "workspace", ["autonomy_level"]),
        (2, "read_only", ["autonomy_level", "file_access"]),
        (3, "read_only", ["file_access"]),
        (4, "read_only", ["file_access"]),
    ],
)
def test_blocked_build_has_no_project_or_run_side_effects(tmp_path, monkeypatch, autonomy, access, controls):
    repo = _new_repo(tmp_path)
    project = Mock(side_effect=AssertionError("A blocked request created a project"))
    stage = Mock(side_effect=AssertionError("A blocked request staged attachments"))
    credential = AsyncMock(side_effect=AssertionError("A blocked request requested credentials"))
    spawn = AsyncMock(side_effect=AssertionError("A blocked request spawned a worker"))
    monkeypatch.setattr(routes, "_new_task_project_root", project)
    monkeypatch.setattr(routes, "stage_code_attachments", stage)
    monkeypatch.setattr(routes, "prepare_code_oauth_credential", credential)
    monkeypatch.setattr(routes.asyncio, "create_subprocess_exec", spawn)
    request = {
        "message": "Create a synthetic counter",
        "model_id": "gpt-5.6-sol",
        "autonomy_level": autonomy,
        "file_access": access,
        "thomas_guardrails": "fortress",
        "docs": [{"name": "input.txt", "text": "input"}],
    }

    async def check(client):
        response = await client.post("/api/evolve/agent/send", json=request)
        payload = await response.json()
        assert response.status == 409 and payload["code"] == "execution_settings_blocked"
        assert payload["blocked_controls"] == controls
        assert "Build has not started" in payload["error"] and "Tools" in payload["error"]
        assert "dry-run" not in payload["error"] and "plan" not in payload["error"]
        assert not any(key in payload for key in ("run_id", "conversation_id", "proof", "artifacts"))
        if "autonomy_level" in controls:
            assert "Agent or Full" in payload["error"]
        if "file_access" in controls:
            assert "Read only" in payload["error"] and "Workspace or Project" in payload["error"]

    _drive(repo, check)
    project.assert_not_called()
    stage.assert_not_called()
    credential.assert_not_awaited()
    spawn.assert_not_awaited()
    assert request["autonomy_level"] == autonomy and request["file_access"] == access
    assert request["thomas_guardrails"] == "fortress"


@pytest.mark.parametrize("autonomy", [3, 4])
def test_allowed_controls_continue_to_existing_project_resolution(tmp_path, monkeypatch, autonomy):
    repo = _new_repo(tmp_path)
    project = Mock(side_effect=routes.forge_code_projects.ForgeCodeProjectError("reached project resolution"))
    monkeypatch.setattr(routes, "_new_task_project_root", project)

    async def check(client):
        response = await client.post(
            "/api/evolve/agent/send",
            json={
                "message": "Create a synthetic counter",
                "model_id": "gpt-5.6-sol",
                "autonomy_level": autonomy,
                "file_access": "workspace",
                "thomas_guardrails": "fortress",
            },
        )
        payload = await response.json()
        assert response.status == 400 and payload["code"] == "invalid_project_root"
        assert payload["error"] == "reached project resolution"

    _drive(repo, check)
    project.assert_called_once()


def test_actual_build_ui_explains_block_and_retries_current_controls():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the actual-source UI harness")
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            node,
            str(repo / "tests/web_node/code_settings_blocked.mjs"),
            str(repo / "thomas/server/web/js/unified_code_lifecycle.js"),
            str(repo / "thomas/server/web/js/unified_code_mode.js"),
            str(repo / "thomas/server/web/js/unified_code_events.js"),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
