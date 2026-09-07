"""The chat shows what each reply and the whole chat cost (frontier parity: Claude Code /cost, Codex /status)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "thomas" / "server" / "web" / "js" / "cost_readout.js"
DRIVER = ROOT / "tests" / "web_node" / "cost_readout.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_readout_folds_the_stream_and_prices_like_the_cost_tracker() -> None:
    out = subprocess.run(
        ["node", str(DRIVER), str(MODULE)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False
    )
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])

    assert report["model_after_receipt"] == "gpt-4o"
    assert report["provider_after_receipt"] == "openai"
    assert report["turn_total"] == 1540
    assert report["session_total"] == 20300
    # 1000 in at $0.005/1k + 1000 out at $0.015/1k
    assert report["usd_known"] == pytest.approx(0.02)
    # provider:model key wins, case-insensitively, exactly as CostTracker._get_price
    assert report["usd_provider_keyed"] == pytest.approx(0.01)
    # an unknown model prices at the server's declared defaults, never at zero
    assert report["usd_unknown_uses_defaults"] == pytest.approx(0.002)
    # no table at all: no number, rather than an invented one
    assert report["usd_without_table"] is None
    assert report["line_with_prices"] == "This reply 1.2k in · 340 out · ~$0.0111 · This chat 20.3k · ~$0.1245"
    assert report["line_without_prices"] == "This reply 1.2k in · 340 out · This chat 20.3k"
    assert report["line_before_any_reply"] == ""
    assert report["done_without_usage_keeps_last"] == 1540
    assert report["compact"] == ["0", "999", "1.5k", "20.3k", "1.25M"]
    assert report["floored_session_line"] == "This reply 1k in · 0 out · ~$0.0050 · This chat 3k · ≥$0.0150"
    assert report["cached_line"] == "This reply 1.2k in (1k cached) · 30 out"
    # No count reached the server: the line says so rather than pricing zeros.
    assert report["unreported_line"] == "This reply · usage not reported by ollama"
    # A local provider is never priced at the cloud defaults.
    assert report["local_line"] == "This reply 4.1k in · 36 out · local, no charge · This chat 4.1k"
    assert report["local_row_line"] == "This reply 4.1k in · 2 out · local, no charge · This chat 4.1k"


def test_the_chat_page_carries_the_readout_once() -> None:
    from thomas.server.app_middleware_helpers import inject_ask_user_panel

    once = inject_ask_user_panel("<html><body><p>hi</p></body></html>")
    assert once.count("cost_readout.js") == 1
    assert inject_ask_user_panel(once) == once
