import json
from datetime import date
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
    detail = ct.today_by_model_detail()["gpt-4o"]
    assert detail["tokens"]["total"] == 2000
    assert detail["total_tokens"] == 2000
    day = ct.by_day(days=1)[0]
    assert day["total_tokens"] == 2000
    assert day["tokens"]["prompt"] == 1000
    assert day["by_model_detail"]["gpt-4o"]["tokens"]["completion"] == 1000


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


def test_historical_negative_ledger_values_do_not_subtract_from_totals(tmp_path: Path):
    spend = tmp_path / "spend.jsonl"
    toml = tmp_path / "thomas.toml"
    toml.write_text("", encoding="utf-8")
    today = date.today().isoformat()
    rows = [
        {
            "day": today,
            "model": "gpt-4o",
            "provider": "openai",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "usd_total": 0.25,
        },
        {
            "day": today,
            "model": "gpt-4o",
            "provider": "openai",
            "prompt_tokens": -1000,
            "completion_tokens": -500,
            "usd_total": -9.99,
        },
    ]
    spend.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    ct = CostTracker(spend_path=spend, toml_path=toml)

    assert ct.today_usd() == 0.25
    assert ct.today_tokens() == {"prompt": 100, "completion": 50, "total": 150}
    assert ct.today_call_count() == 2
