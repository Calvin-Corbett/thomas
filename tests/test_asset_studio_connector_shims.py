from __future__ import annotations

import argparse
import json
from pathlib import Path

from thomas.asset_studio import connector_shims as shims


def test_comfyui_queue_prompt_uses_http_post(monkeypatch):
    calls = {}

    def _fake_http_request_json(url, *, method, headers, timeout_s, body=None):  # noqa: ANN001
        calls["url"] = str(url)
        calls["method"] = str(method)
        calls["headers"] = dict(headers)
        calls["timeout_s"] = float(timeout_s)
        calls["body"] = dict(body or {})
        return {"prompt_id": "pid-123", "number": 17}

    monkeypatch.setattr(shims, "_http_request_json", _fake_http_request_json)
    args = argparse.Namespace(
        server_url="http://127.0.0.1:8188",
        workflow_json='{"3": {"inputs": {}}}',
        workflow_file="",
        client_id="cid-1",
        timeout_s=11.0,
        output="",
    )
    out = shims.comfyui_queue_prompt(args)
    assert out["ok"] is True
    assert out["prompt_id"] == "pid-123"
    assert calls["url"].endswith("/prompt")
    assert calls["method"] == "POST"
    assert calls["body"]["client_id"] == "cid-1"
    assert isinstance(calls["body"]["prompt"], dict)


def test_comfyui_get_history_reads_prompt_history(monkeypatch):
    def _fake_http_get_json(url, *, headers, timeout_s):  # noqa: ANN001
        _ = headers
        _ = timeout_s
        assert str(url).endswith("/history/pid-9")
        return {
            "pid-9": {
                "status": {"completed": True},
                "outputs": {
                    "5": {
                        "images": [{"filename": "x.png"}],
                    }
                },
            }
        }

    monkeypatch.setattr(shims, "_http_get_json", _fake_http_get_json)
    args = argparse.Namespace(
        server_url="http://127.0.0.1:8188",
        prompt_id="pid-9",
        timeout_s=12.0,
        output="",
    )
    out = shims.comfyui_get_history(args)
    assert out["ok"] is True
    assert out["prompt_id"] == "pid-9"
    assert int(out["output_nodes"]) == 1


def test_otio_validate_timeline_json_fallback(tmp_path: Path):
    timeline = tmp_path / "sample.otio"
    timeline.write_text(
        json.dumps(
            {
                "OTIO_SCHEMA": "Timeline.1",
                "tracks": {
                    "children": [
                        {"children": [{"name": "clip-a"}, {"name": "clip-b"}]},
                        {"children": [{"name": "clip-c"}]},
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(input_path=str(timeline), output="")
    out = shims.otio_validate_timeline(args)
    assert out["ok"] is True
    assert out["exists"] is True
    assert out["schema"] == "Timeline.1"
    assert int(out["track_count"]) == 2
    assert int(out["clip_count"]) == 3

