import json
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


def test_session_includes_external_appends_after_tracker_init(tmp_path: Path):
    spend = tmp_path / "spend.jsonl"
    toml = tmp_path / "thomas.toml"
    toml.write_text("", encoding="utf-8")

    ct = CostTracker(spend_path=spend, toml_path=toml)

    spend.write_text(
        json.dumps(
            {
                "ts": "2026-04-03T16:45:00",
                "day": "2026-04-03",
                "model": "gpt-5.3-codex",
                "provider": "codex",
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "usd_prompt": 0.01,
                "usd_completion": 0.02,
                "usd_total": 0.03,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    assert ct.session_call_count() == 1
    assert ct.session_tokens()["total"] == 150
    assert ct.session_by_model_detail()["gpt-5.3-codex"]["total_tokens"] == 150


def test_session_reset_advances_shared_ledger_marker(tmp_path: Path):
    spend = tmp_path / "spend.jsonl"
    toml = tmp_path / "thomas.toml"
    toml.write_text("", encoding="utf-8")

    ct = CostTracker(spend_path=spend, toml_path=toml)
    ct.record(model="gpt-4o", provider="openai", prompt_tokens=100, completion_tokens=20)
    assert ct.session_call_count() == 1

    ct.reset_session()
    assert ct.session_call_count() == 0

    with spend.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "ts": "2026-04-03T16:46:00",
                    "day": "2026-04-03",
                    "model": "gpt-5.3-codex",
                    "provider": "codex",
                    "prompt_tokens": 50,
                    "completion_tokens": 10,
                    "usd_prompt": 0.004,
                    "usd_completion": 0.003,
                    "usd_total": 0.007,
                },
                separators=(",", ":"),
            )
            + "\n"
        )

    assert ct.session_call_count() == 1
    assert ct.session_tokens()["total"] == 60
    assert list(ct.session_by_model_detail()) == ["gpt-5.3-codex"]
