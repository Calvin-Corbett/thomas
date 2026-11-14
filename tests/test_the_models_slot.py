"""The models slot keeps its promise: a provider that does not meet the contract fails here, not inside a turn.

Two providers are held to it. ``Models`` must satisfy ``LLMSeam`` (what the kernel's LLM service offers), and ``LLMClient``
must satisfy ``ModelClient`` (what callers may touch on a client). Before this, ``LLMSeam`` asked for ``stream`` while
``LLMClient`` has ``stream_chat``, so the class its docstring named did not satisfy it and no test read it.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.agent.kernel_wiring import default_kernel, get_kernel, set_kernel
from thomas.core import llm_adapters, llm_client, llm_slot
from thomas.core.config import ModelConfig
from thomas.core.kernel import LLM, SeamViolation, require, seam_report
from thomas.core.kernel.seams import LLMSeam
from thomas.core.llm_slot import ModelClient, Models, models


@pytest.fixture(autouse=True)
def _isolate():
    set_kernel(None)
    yield
    set_kernel(None)


def _cfg(name: str = "main", **fields: Any) -> ModelConfig:
    return ModelConfig(name=name, **fields)


class _Recorder:
    """Stands in for a client class: remembers how it was built."""

    def __init__(self, config: Any, **options: Any) -> None:
        self.config = config
        self.options = options
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


def _app_config(*, enabled: bool = True, auto: bool = False, chain: list[ModelConfig] | None = None) -> Any:
    profiles = {"main": _cfg("main", model="m1"), "other": _cfg("other", model="m2")}
    failover = SimpleNamespace(
        enabled=enabled, chat_auto_failover=auto, cooldown_seconds=17, fallback_on_auth_error=True
    )
    return SimpleNamespace(
        default_model="main",
        failover=failover,
        get_model=lambda name=None: profiles[name or "main"],
        failover_chain=lambda name: list(chain or []) if enabled else [],
    )


# -- the two contracts --------------------------------------------------------------------------------------------


def test_models_satisfies_the_llm_seam() -> None:
    assert isinstance(models(), LLMSeam)
    kernel = default_kernel()
    assert require(kernel.root, LLM, LLMSeam) is models()


def test_a_provider_missing_part_of_the_seam_is_refused_where_it_is_registered() -> None:
    class Old:
        async def stream(self, *args: Any, **kwargs: Any) -> Any: ...

    kernel = default_kernel(llm=Old())
    with pytest.raises(SeamViolation) as caught:
        require(kernel.root, LLM, LLMSeam)
    assert "LLM" in str(caught.value) or "llm" in str(caught.value)


def test_llm_client_satisfies_the_model_client_contract() -> None:
    client = llm_client.LLMClient(_cfg())
    assert isinstance(client, ModelClient)


def test_llm_client_takes_the_calls_the_contract_names() -> None:
    stream = inspect.signature(llm_client.LLMClient.stream_chat).parameters
    assert list(stream)[:3] == ["self", "messages", "tools"]
    assert stream["turn_user_content"].kind is inspect.Parameter.KEYWORD_ONLY
    chat = inspect.signature(llm_client.LLMClient.chat).parameters
    assert list(chat)[:3] == ["self", "messages", "tools"]
    assert inspect.iscoroutinefunction(llm_client.LLMClient.chat)
    assert inspect.iscoroutinefunction(llm_client.LLMClient.close)
    assert inspect.isasyncgenfunction(llm_client.LLMClient.stream_chat)


def test_a_client_missing_a_call_does_not_meet_the_contract() -> None:
    class NoClose:
        config = None
        session_usage = None

        def stream_chat(self, messages, tools=None, *, turn_user_content=None): ...
        async def chat(self, messages, tools=None): ...
        def reset_runtime_trace(self): ...
        def runtime_trace(self): ...
        def set_budget_scope(self, scope): ...

    assert not isinstance(NoClose(), ModelClient)


# -- the kernels ---------------------------------------------------------------------------------------------------


def test_both_ways_to_get_a_default_kernel_carry_the_slot() -> None:
    for kernel in (default_kernel(), get_kernel()):
        assert kernel.root[LLM] is models()
        assert "llm" not in seam_report(kernel)["unfilled"]


def test_a_host_can_still_hand_in_its_own_llm() -> None:
    assert default_kernel(llm="CLIENT").root[LLM] == "CLIENT"


# -- open / profile / session ----------------------------------------------------------------------------------------


def test_open_builds_the_default_class_with_exactly_the_arguments_given() -> None:
    cfg = _cfg()
    client = models().open(cfg, failover_enabled=False, fallback_configs=[])
    assert isinstance(client, llm_client.LLMClient)
    assert client.config is cfg
    assert client._failover_enabled is False


def test_open_uses_the_class_the_caller_names(monkeypatch: pytest.MonkeyPatch) -> None:
    built = models().open("CFG", default=_Recorder, a=1)
    assert isinstance(built, _Recorder)
    assert (built.config, built.options) == ("CFG", {"a": 1})


def test_open_looks_the_class_up_when_called(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "LLMClient", _Recorder)
    assert isinstance(models().open("CFG"), _Recorder)


def test_profile_carries_the_failover_chain_and_chat_failover_rule() -> None:
    other = _cfg("other", model="m2")
    config = _app_config(enabled=True, auto=False, chain=[other])
    built = models().profile(config, "main", default=_Recorder)
    assert built.config.name == "main"
    assert built.options == {
        "fallback_configs": [other],
        "failover_enabled": False,
        "failover_cooldown_s": 17,
        "failover_on_auth_error": True,
    }
    auto = models().profile(_app_config(enabled=True, auto=True, chain=[other]), default=_Recorder)
    assert auto.options["failover_enabled"] is True


def test_profile_lets_a_caller_keep_its_own_failover_rule() -> None:
    config = _app_config(enabled=True, auto=False, chain=[_cfg("other")])
    built = models().profile(config, "main", default=_Recorder, failover_enabled=config.failover.enabled)
    assert built.options["failover_enabled"] is True
    over = models().profile(config, "main", default=_Recorder, failover_cooldown_s=1)
    assert over.options["failover_cooldown_s"] == 1


def test_credentials_reach_the_profile_and_its_failover_models_and_the_undo_takes_them_back() -> None:
    other = _cfg("other")
    config = _app_config(chain=[other])
    seen: list[tuple[str, str]] = []

    def resolve(cfg: Any, profile: str) -> Any:
        seen.append((cfg.name, profile))
        return _cfg(cfg.name, api_key="embedded")

    undo = models().credentials(resolve)
    try:
        built = models().profile(config, "main", default=_Recorder)
    finally:
        undo()
    assert built.config.api_key == "embedded"
    assert built.options["fallback_configs"][0].api_key == "embedded"
    assert seen == [("main", "main"), ("other", "other")]
    assert models().profile(config, "main", default=_Recorder).config.api_key == ""
    undo()


def test_the_newest_credentials_resolver_answers_and_the_older_returns_when_it_goes() -> None:
    config = _app_config()
    first = models().credentials(lambda cfg, profile: _cfg(cfg.name, api_key="first"))
    second = models().credentials(lambda cfg, profile: _cfg(cfg.name, api_key="second"))
    try:
        assert models().profile(config, default=_Recorder).config.api_key == "second"
        second()
        assert models().profile(config, default=_Recorder).config.api_key == "first"
    finally:
        second()
        first()
    assert models().profile(config, default=_Recorder).config.api_key == ""


async def test_session_closes_the_client_on_the_way_out_even_after_an_error() -> None:
    kept: list[_Recorder] = []
    with pytest.raises(RuntimeError):
        async with models().session("CFG", default=_Recorder) as client:
            kept.append(client)
            raise RuntimeError("boom")
    assert kept[0].closed == 1


# -- adapters ----------------------------------------------------------------------------------------------------------


def test_an_adapter_is_found_by_provider_and_the_undo_gives_back_what_was_there() -> None:
    async def one(*args: Any, **kwargs: Any):
        yield 1

    async def two(*args: Any, **kwargs: Any):
        yield 2

    assert llm_adapters.lookup("my-provider") is None
    undo_one = models().adapter("my_provider", one)
    undo_two = models().adapter("My-Provider", two)
    try:
        assert llm_adapters.lookup("my-provider") is two
        undo_two()
        assert llm_adapters.lookup("my_provider") is one
        undo_two()  # again: nothing more to undo
        assert llm_adapters.lookup("my_provider") is one
    finally:
        undo_one()
    assert llm_adapters.lookup("my_provider") is None


def test_an_older_undo_does_not_remove_a_newer_adapter() -> None:
    async def one(*args: Any, **kwargs: Any):
        yield 1

    async def two(*args: Any, **kwargs: Any):
        yield 2

    undo_one = models().adapter("older_undo", one)
    undo_two = models().adapter("older_undo", two)
    try:
        undo_one()
        assert llm_adapters.lookup("older_undo") is two
    finally:
        undo_two()
    assert llm_adapters.lookup("older_undo") is None


def test_an_adapter_needs_a_name_and_a_callable() -> None:
    with pytest.raises(ValueError):
        llm_adapters.register("", lambda *a, **k: None)
    with pytest.raises(TypeError):
        llm_adapters.register("x", None)  # type: ignore[arg-type]


def test_the_slot_is_one_object() -> None:
    assert models() is llm_slot.models() and isinstance(models(), Models)
