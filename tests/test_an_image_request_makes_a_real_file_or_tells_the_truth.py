"""An image request either produces a real PNG on disk or says exactly why it cannot.

The tool must never fake an image and never fail silently:

- with a working credential and a (faked) provider response, the PNG bytes land
  in the workspace and the result carries the real path;
- with no credential anywhere, the result is the honest remedy sentence naming
  the missing key and where to add it -- including the truth that the ChatGPT
  subscription sign-in cannot generate images (verified live: HTTP 401,
  missing scope ``api.model.images.request``);
- with a credential the provider rejects, the upstream error text is preserved;
- the tool is visible in the registry either way, so the model can relay the
  real situation instead of silently lacking the capability.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from thomas.core.config import ModelConfig
from thomas.tools.image_generation import (
    NO_CREDENTIAL_REMEDY,
    ImageGenerateTool,
    register_image_generation_tools,
)
from thomas.tools.registry import ToolRegistry

# A real, valid 1x1 PNG.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
TINY_PNG_B64 = base64.b64encode(TINY_PNG).decode("ascii")


def _openai_profile() -> dict[str, ModelConfig]:
    return {
        "openai": ModelConfig(
            name="openai",
            provider="openai_compat",
            base_url="https://api.openai.com/v1",
            api_key="sk-test-fake",
            model="gpt-4o-mini",
        )
    }


def _gemini_env() -> dict[str, str]:
    return {"GEMINI_API_KEY": "AIza-test-fake"}


@pytest.mark.asyncio
async def test_success_writes_the_png_and_returns_its_path(tmp_path: Path) -> None:
    calls: list[dict] = []

    async def fake_post(url, headers, json_body, timeout_s):
        calls.append({"url": url, "json": json_body})
        return 200, {"data": [{"b64_json": TINY_PNG_B64}]}

    tool = ImageGenerateTool(
        workspace=tmp_path,
        model_configs=_openai_profile(),
        env={},
        http_post=fake_post,
    )
    result = await tool.safe_execute({"prompt": "a tiny red square"})

    assert result.ok, result.error
    files = result.data["files"]
    assert len(files) == 1
    written = Path(files[0])
    assert written.is_file()
    assert written.read_bytes() == TINY_PNG
    assert written.parent == tmp_path
    assert written.suffix == ".png"
    assert result.data["provider"] == "openai"
    assert "a tiny red square" in result.data["description"]
    assert calls and calls[0]["url"].endswith("/images/generations")
    assert calls[0]["json"]["prompt"] == "a tiny red square"


@pytest.mark.asyncio
async def test_count_writes_that_many_files(tmp_path: Path) -> None:
    async def fake_post(url, headers, json_body, timeout_s):
        n = int(json_body.get("n") or 1)
        return 200, {"data": [{"b64_json": TINY_PNG_B64} for _ in range(n)]}

    tool = ImageGenerateTool(
        workspace=tmp_path,
        model_configs=_openai_profile(),
        env={},
        http_post=fake_post,
    )
    result = await tool.safe_execute({"prompt": "three squares", "count": 3})

    assert result.ok, result.error
    assert len(result.data["files"]) == 3
    for f in result.data["files"]:
        assert Path(f).is_file()


@pytest.mark.asyncio
async def test_gemini_key_alone_is_enough(tmp_path: Path) -> None:
    async def fake_post(url, headers, json_body, timeout_s):
        assert "generativelanguage.googleapis.com" in url
        return 200, {
            "candidates": [{"content": {"parts": [{"inlineData": {"data": TINY_PNG_B64}}]}}]
        }

    tool = ImageGenerateTool(
        workspace=tmp_path,
        model_configs={},
        env=_gemini_env(),
        http_post=fake_post,
    )
    result = await tool.safe_execute({"prompt": "a tiny blue square"})

    assert result.ok, result.error
    assert Path(result.data["files"][0]).read_bytes() == TINY_PNG
    assert result.data["provider"] == "gemini"


@pytest.mark.asyncio
async def test_no_credential_returns_the_honest_remedy_and_writes_nothing(tmp_path: Path) -> None:
    async def fake_post(url, headers, json_body, timeout_s):  # pragma: no cover
        raise AssertionError("no HTTP call may happen without a credential")

    tool = ImageGenerateTool(
        workspace=tmp_path,
        model_configs={},
        env={},
        http_post=fake_post,
    )
    result = await tool.safe_execute({"prompt": "anything"})

    assert not result.ok
    assert result.error == NO_CREDENTIAL_REMEDY
    # The remedy names both real fixes and tells the ChatGPT-subscription truth.
    assert "OPENAI_API_KEY" in result.error
    assert "GEMINI_API_KEY" in result.error
    assert "api.model.images.request" in result.error
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_a_rejected_key_surfaces_the_upstream_error(tmp_path: Path) -> None:
    async def fake_post(url, headers, json_body, timeout_s):
        return 401, {"error": {"message": "Incorrect API key provided: sk-test-fake."}}

    tool = ImageGenerateTool(
        workspace=tmp_path,
        model_configs=_openai_profile(),
        env={},
        http_post=fake_post,
    )
    result = await tool.safe_execute({"prompt": "anything"})

    assert not result.ok
    assert "Incorrect API key provided" in result.error
    assert "401" in result.error
    assert list(tmp_path.iterdir()) == []


def test_the_registry_exposes_the_tool_even_without_credentials(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_image_generation_tools(registry, config=None, workspace=tmp_path)

    tool = registry.get("image.generate")
    assert tool is not None
    spec_names = [spec.name for spec in (t.get_spec() for t in [tool])]
    assert "image.generate" in spec_names
    # The model-facing description must promise honesty, not capability.
    assert "never pretend" in tool.description.lower() or "explains exactly" in tool.description.lower()


def test_the_chat_worker_toolset_includes_image_generate(tmp_path: Path) -> None:
    """``_build_tools`` is what both the chat agent and the delegation worker use.

    This builds the REAL registry (not a source grep) so a broken import or a
    skipped registration fails here, the way it would fail live.
    """
    import dataclasses

    from thomas.core.config import load_config
    from thomas.server.app_helpers import _build_tools

    cfg = load_config()
    cfg = dataclasses.replace(cfg, tools=dataclasses.replace(cfg.tools, sandbox_root=str(tmp_path)))
    registry = _build_tools(cfg)
    assert registry.get("image.generate") is not None


def test_the_code_agent_loop_toolset_includes_image_generate() -> None:
    """The Code engine builds its registry inline inside ``_agent_loop_pass_async``;
    that pass cannot run without a live LLM, so wiring is asserted at source level.
    """
    import inspect

    from thomas.forge.anvil import dispatch_agent_loop

    source = inspect.getsource(dispatch_agent_loop._agent_loop_pass_async)
    assert "register_image_generation_tools" in source
