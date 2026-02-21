import base64
import json
from pathlib import Path

import pytest

from thomas.nodes.p043_nodes_screen_capture_action import (
    NodesScreenCaptureConfigError,
    NodesScreenCaptureExternalError,
    NodesScreenCaptureInputError,
    NodesScreenCaptureRequest,
    build_transport_from_config,
    parse_nodes_screen_capture_request,
    run_nodes_screen_capture,
)


# A tiny 1x1 PNG (transparent) to keep tests lightweight.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/6X9l2cAAAAASUVORK5CYII="
)


class _FakeTransport:
    def __init__(self, payload: bytes = _PNG_1X1, *, exc: Exception | None = None) -> None:
        self._payload = payload
        self._exc = exc

    async def capture_screen(self, node_id: str, *, image_format: str, timeout_s: float) -> bytes:
        if self._exc:
            raise self._exc
        return self._payload


@pytest.mark.asyncio
async def test_screen_capture_success_writes_file(tmp_path: Path) -> None:
    req = parse_nodes_screen_capture_request(
        {
            "node_id": "node-123",
            "image_format": "png",
            "save_path": str(tmp_path / "shot.png"),
            "include_image_b64": False,
            "timeout_s": 1,
        }
    )

    res = await run_nodes_screen_capture(req, transport=_FakeTransport())

    assert res.node_id == "node-123"
    assert res.image_format == "png"
    assert res.bytes_captured == len(_PNG_1X1)
    assert res.saved_path is not None
    assert Path(res.saved_path).exists()
    assert res.image_b64 is None


@pytest.mark.asyncio
async def test_screen_capture_appends_extension_when_missing(tmp_path: Path) -> None:
    req = parse_nodes_screen_capture_request(
        {
            "node_id": "node-123",
            "image_format": "png",
            "save_path": str(tmp_path / "shot"),  # no extension
            "include_image_b64": False,
            "timeout_s": 1,
        }
    )

    res = await run_nodes_screen_capture(req, transport=_FakeTransport())

    assert res.saved_path is not None
    assert res.saved_path.endswith(".png")
    assert Path(res.saved_path).exists()


@pytest.mark.asyncio
async def test_screen_capture_directory_hint_uses_inferred_filename(tmp_path: Path) -> None:
    req = parse_nodes_screen_capture_request(
        {
            "node_id": "node/unsafe",
            "image_format": "png",
            "save_path": str(tmp_path) + "/",  # trailing slash hint
            "include_image_b64": False,
            "timeout_s": 1,
        }
    )

    res = await run_nodes_screen_capture(req, transport=_FakeTransport())

    assert res.saved_path is not None
    out = Path(res.saved_path)
    assert out.exists()
    assert str(out.parent) == str(tmp_path)


@pytest.mark.asyncio
async def test_screen_capture_success_inline_base64() -> None:
    req = parse_nodes_screen_capture_request(
        {
            "node_id": "n",
            "image_format": "png",
            "save_path": None,
            "include_image_b64": True,
            "timeout_s": 1,
        }
    )

    res = await run_nodes_screen_capture(req, transport=_FakeTransport())

    assert res.saved_path is None
    assert res.image_b64 == base64.b64encode(_PNG_1X1).decode("ascii")


@pytest.mark.asyncio
async def test_screen_capture_no_base64_by_default() -> None:
    req = parse_nodes_screen_capture_request(
        {
            "node_id": "n",
            "image_format": "png",
            "save_path": None,
            "include_image_b64": False,
            "timeout_s": 1,
        }
    )

    res = await run_nodes_screen_capture(req, transport=_FakeTransport())

    assert res.saved_path is None
    assert res.image_b64 is None


@pytest.mark.asyncio
async def test_screen_capture_invalid_input_is_deterministic() -> None:
    with pytest.raises(NodesScreenCaptureInputError) as ei:
        parse_nodes_screen_capture_request({"node_id": "", "image_format": "png"})
    assert ei.value.code == "invalid_input"
    assert str(ei.value) == "node_id must be a non-empty string"

    with pytest.raises(NodesScreenCaptureInputError) as ei2:
        parse_nodes_screen_capture_request({"node_id": "n", "image_format": "tiff"})
    assert ei2.value.code == "invalid_input"
    assert "image_format must be one of" in str(ei2.value)


@pytest.mark.asyncio
async def test_screen_capture_missing_config_is_deterministic() -> None:
    req = NodesScreenCaptureRequest(node_id="n")
    with pytest.raises(NodesScreenCaptureConfigError) as ei:
        await run_nodes_screen_capture(req, transport=None, config={})
    assert ei.value.code == "missing_config"
    assert str(ei.value) == "missing nodes base URL (nodes_base_url)"


@pytest.mark.asyncio
async def test_screen_capture_external_failure_is_deterministic() -> None:
    req = NodesScreenCaptureRequest(node_id="n")
    with pytest.raises(NodesScreenCaptureExternalError) as ei:
        await run_nodes_screen_capture(req, transport=_FakeTransport(exc=RuntimeError("boom")))
    assert ei.value.code == "external_failure"
    assert str(ei.value) == "screen capture failed"


def test_build_transport_from_config_requires_base_url() -> None:
    with pytest.raises(NodesScreenCaptureConfigError):
        build_transport_from_config({})


def test_cli_json_failure_missing_node_id(capsys) -> None:
    from thomas.cli.commands.nodes import p043_nodes_screen_capture_action as cli_mod
    rc = cli_mod.cli_main(["--json"])
    assert rc == 2
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
    assert payload["error"]["message"] == "node_id is required"


def test_cli_json_success(monkeypatch, capsys) -> None:
    from thomas.cli.commands.nodes import p043_nodes_screen_capture_action as cli_mod
    from thomas.nodes.p043_nodes_screen_capture_action import NodesScreenCaptureResult

    def _fake_run(req, config=None, transport=None):
        return NodesScreenCaptureResult(
            node_id=req.node_id,
            image_format=req.image_format,
            captured_at="2020-01-01T00:00:00+00:00",
            bytes_captured=123,
            saved_path="/tmp/shot.png",
            image_b64=None,
        )

    monkeypatch.setattr(cli_mod, "run_nodes_screen_capture_sync", _fake_run)

    rc = cli_mod.cli_main(["node-1", "--json", "--out", "/tmp/shot.png"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["result"]["node_id"] == "node-1"
    assert payload["result"]["saved_path"] == "/tmp/shot.png"
