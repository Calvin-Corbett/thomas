"""A model served from this machine costs nothing, and the receipt says so (2026-09-07).

The chat on :8977 ran on profile ``local`` (qwen2.5-coder:7b behind Ollama at
127.0.0.1:11434) and every receipt priced it at the cloud defaults: ``This
reply 4.1k in · 2 out · ~$0.0082``. The profile's provider is
``openai_compat``, so no provider-name list can know it is local; the server
can, from the base URL it is configured with.

The cost tracker now publishes a zero row, flagged ``local``, for every
configured model whose base URL points at this machine or a private network,
unless ``[pricing]`` names that model explicitly. The readout and the Token
Economy both read that row, so the receipt says ``local, no charge`` and the
ledger records zero for it.
"""

from __future__ import annotations

from pathlib import Path

from thomas.core.cost_tracker import CostTracker, is_local_base_url

TOML = """
[models.local]
provider = "openai_compat"
model = "qwen2.5-coder:7b"
base_url = "http://127.0.0.1:11434/v1"

[models.lan]
provider = "vllm"
model = "llama-3-70b"
base_url = "http://192.168.1.40:8000/v1"

[models.cloud]
provider = "openai"
model = "gpt-4o"
base_url = "https://api.openai.com/v1"

[pricing."openai_compat:paid-local"]
input_per_1k = 0.001
output_per_1k = 0.002

[models.paid]
provider = "openai_compat"
model = "paid-local"
base_url = "http://127.0.0.1:9999/v1"
"""


def _tracker(tmp_path: Path) -> CostTracker:
    toml = tmp_path / "thomas.toml"
    toml.write_text(TOML, encoding="utf-8")
    return CostTracker(spend_path=tmp_path / "spend.jsonl", toml_path=toml)


def test_a_loopback_or_private_base_url_is_local() -> None:
    assert is_local_base_url("http://127.0.0.1:11434/v1")
    assert is_local_base_url("http://localhost:1234")
    assert is_local_base_url("http://[::1]:8000/v1")
    assert is_local_base_url("http://192.168.1.40:8000/v1")
    assert is_local_base_url("http://10.0.0.7/v1")
    assert not is_local_base_url("https://api.openai.com/v1")
    assert not is_local_base_url("")


def test_a_local_model_prices_at_zero_and_says_so(tmp_path: Path) -> None:
    ct = _tracker(tmp_path)
    row = ct._get_price("qwen2.5-coder:7b", "openai_compat")
    assert row["input_per_1k"] == 0.0 and row["output_per_1k"] == 0.0 and row.get("local") is True
    assert ct._get_price("llama-3-70b", "vllm").get("local") is True
    table = ct.pricing_table()
    assert table["openai_compat:qwen2.5-coder:7b"]["local"] is True
    assert table["openai_compat:qwen2.5-coder:7b"]["input_per_1m"] == 0.0
    ct.record("qwen2.5-coder:7b", 4100, 36, provider="openai_compat")
    assert ct.session_usd() == 0.0 and ct.session_tokens()["total"] == 4136


def test_cloud_and_explicitly_priced_models_are_untouched(tmp_path: Path) -> None:
    ct = _tracker(tmp_path)
    assert ct._get_price("gpt-4o", "openai")["input_per_1k"] == 0.005
    assert "local" not in ct.pricing_table()["gpt-4o"]
    paid = ct._get_price("paid-local", "openai_compat")
    assert paid["input_per_1k"] == 0.001 and not paid.get("local")
