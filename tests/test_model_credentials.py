"""One credentials function behind the server and the worker copies."""

from __future__ import annotations

from dataclasses import dataclass

from thomas.server.model_credentials import embed_credentials


@dataclass
class _Cfg:
    name: str = "p"
    provider: str = "openai"
    api_key: str = ""
    api_key_secret_name: str = ""


class _Store:
    def __init__(self, **items: str) -> None:
        self.items = dict(items)

    def get(self, key: str) -> str | None:
        return self.items.get(key)

    def __bool__(self) -> bool:
        return True


def test_none_config_gives_none() -> None:
    assert embed_credentials(None, "p", _Store()) is None


def test_named_secret_is_embedded_into_a_copy() -> None:
    cfg = _Cfg(api_key_secret_name="k")
    out = embed_credentials(cfg, "p", _Store(k="sekret"))
    assert out.api_key == "sekret"
    assert cfg.api_key == ""


def test_profile_name_fallback_is_off_by_default() -> None:
    out = embed_credentials(_Cfg(), "p", _Store(p="sekret"))
    assert out.api_key == ""


def test_profile_name_fallback_looks_under_the_profile() -> None:
    out = embed_credentials(_Cfg(), "p", _Store(p="sekret"), profile_name_fallback=True)
    assert out.api_key == "sekret"


def test_no_store_returns_the_copy_untouched() -> None:
    assert embed_credentials(_Cfg(api_key="a"), "p", None).api_key == "a"
