from pathlib import Path

from thomas.core.cost_tracker import CostTracker, extract_token_usage


def test_extract_usage_common_shapes():
    assert extract_token_usage({"prompt_tokens": 3, "completion_tokens": 4}) == (3, 4)
    assert extract_token_usage({"usage": {"input_tokens": 5, "output_tokens": 6}}) == (5, 6)
    assert extract_token_usage({"usage_metadata": {"prompt_token_count": 7, "candidates_token_count": 8}}) == (7, 8)


def test_record_and_today(tmp_path: Path):
    spend = tmp_path / "spend.jsonl"
    toml = tmp_path / "thomas.toml"
    toml.write_text("", encoding="utf-8")

    ct = CostTracker(spend_path=spend, toml_path=toml)
    ct.record(model="gpt-4o", provider="openai", prompt_tokens=1000, completion_tokens=1000)

    assert ct.today_usd() > 0
    assert ct.today_call_count() == 1
    toks = ct.today_tokens()
    assert toks["total"] == 2000
    bym = ct.by_model()
    assert "gpt-4o" in bym


def test_pricing_override_provider_scoped(tmp_path: Path):
    spend = tmp_path / "spend.jsonl"
    toml = tmp_path / "thomas.toml"
    toml.write_text(
        '[pricing."openai:gpt-4o"]\ninput_per_1k = 0.01\noutput_per_1k = 0.02\n',
        encoding="utf-8",
    )

    ct = CostTracker(spend_path=spend, toml_path=toml)
    ct.record(model="gpt-4o", provider="openai", prompt_tokens=1000, completion_tokens=1000)

    assert abs(ct.today_usd() - 0.03) < 1e-6
