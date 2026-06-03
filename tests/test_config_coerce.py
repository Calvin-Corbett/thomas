"""A malformed numeric override must not crash config loading.

_coerce_types() used to call int()/float() unguarded, so e.g.
THOMAS_MAX_TOKENS=abc raised ValueError and crashed load_config() at boot.
It now drops the bad value so the validated default applies.
"""

from __future__ import annotations

from thomas.core.config import _coerce_types


def test_malformed_numeric_overrides_are_dropped_not_crashing():
    data = {"max_tokens": "abc", "temperature": "hot", "max_tokens_ok": "x"}
    _coerce_types(data)  # must not raise
    # malformed int/float dropped so the dataclass default applies downstream
    assert "max_tokens" not in data
    assert "temperature" not in data


def test_valid_numeric_overrides_still_coerce():
    data = {"max_tokens": "2048", "temperature": "0.7", "top_p": "0.95"}
    _coerce_types(data)
    assert data["max_tokens"] == 2048
    assert data["temperature"] == 0.7
    assert data["top_p"] == 0.95


def test_coerce_recurses_into_nested_model_dicts():
    data = {"models": {"gpt": {"max_tokens": "4096", "temperature": "junk"}}}
    _coerce_types(data)
    assert data["models"]["gpt"]["max_tokens"] == 4096
    assert "temperature" not in data["models"]["gpt"]
