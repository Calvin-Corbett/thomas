from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import thomas.marketplace.asset_studio.comfy_service as comfy_service


@pytest.mark.asyncio
async def test_comfy_status_reports_offline_when_probe_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_url: str, *, timeout_s: float) -> dict[str, object]:  # noqa: ANN001
        _ = timeout_s
        raise RuntimeError("offline")

    monkeypatch.setattr(comfy_service, "_json_get", _raise)
    service = comfy_service.ComfyStudioService()
    status = await service.status(server_url="http://127.0.0.1:8188", timeout_s=1.0)
    assert status["running"] is False
    assert status["managed"] is False
    assert "offline" in str(status["error"])


@pytest.mark.asyncio
async def test_comfy_queue_prompt_delegates_to_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def _fake_queue_prompt(args):  # noqa: ANN001
        captured["server_url"] = args.server_url
        captured["workflow_json"] = args.workflow_json
        return {"ok": True, "prompt_id": "pid-7"}

    monkeypatch.setattr(comfy_service.connector_shims, "comfyui_queue_prompt", _fake_queue_prompt)
    service = comfy_service.ComfyStudioService()
    result = await service.queue_prompt(server_url="http://127.0.0.1:8188", workflow_json='{"3": {"inputs": {}}}')
    assert result["ok"] is True
    assert result["prompt_id"] == "pid-7"
    assert captured["server_url"] == "http://127.0.0.1:8188"
    assert captured["workflow_json"] == '{"3": {"inputs": {}}}'


@pytest.mark.asyncio
async def test_comfy_outputs_builds_view_urls() -> None:
    service = comfy_service.ComfyStudioService()
    service.get_history = AsyncMock(  # type: ignore[assignment]
        return_value={
            "ok": True,
            "server_url": "http://127.0.0.1:8188",
            "prompt_id": "pid-9",
            "status": {"completed": True},
            "history": {
                "outputs": {
                    "7": {
                        "images": [
                            {"filename": "image-1.png", "subfolder": "", "type": "output"},
                        ]
                    }
                }
            },
        }
    )
    outputs = await service.get_outputs(server_url="http://127.0.0.1:8188", prompt_id="pid-9")
    assert outputs["ok"] is True
    assert int(outputs["count"]) == 1
    image = (outputs.get("images") or [])[0]
    assert image["filename"] == "image-1.png"
    assert str(image["url"]).startswith("http://127.0.0.1:8188/view?")
