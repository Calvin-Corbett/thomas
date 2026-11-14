"""``thomas investigate`` builds its model client with ``profile=``, and that is what it does today.

``LLMClient`` has no ``profile`` argument, so the real class refuses the call with a ``TypeError``. This test pins
both halves, so moving the call onto the models slot cannot change either: a client class patched on
``thomas.core.llm`` still receives ``(config, profile=<name>)`` and nothing else, and the real class still refuses.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from thomas.cli.commands import investigate
from thomas.core import llm as llm_module


class _Recorder:
    def __init__(self, config: Any, **options: Any) -> None:
        self.config = config
        self.options = options


def test_the_patched_client_class_gets_the_config_and_the_profile_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_module, "LLMClient", _Recorder)
    config = object()

    llm, llm_call = asyncio.run(investigate._create_llm_call(config, "work-profile"))

    assert isinstance(llm, _Recorder)
    assert llm.config is config
    assert llm.options == {"profile": "work-profile"}
    assert callable(llm_call)


def test_the_real_client_class_still_refuses_the_profile_argument() -> None:
    with pytest.raises(TypeError, match="profile"):
        asyncio.run(investigate._create_llm_call(object(), "work-profile"))
