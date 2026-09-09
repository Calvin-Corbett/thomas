from thomas.core.config import ModelConfig
from thomas.models.capabilities import profile_capability_map


def test_xai_profile_capabilities_include_video_and_audio() -> None:
    cfg = ModelConfig(
        name="xai",
        provider="openai_compat",
        base_url="https://api.x.ai/v1",
        model="grok-4-1-fast-reasoning",
    )
    caps = profile_capability_map(cfg)
    assert caps["chat"] is True
    assert caps["tools"] is True
    assert caps["batch"] is True
    assert caps["video_gen"] is True
    assert caps["stt"] is True
    assert caps["tts"] is True


def test_anthropic_profile_capabilities_disable_video_generation() -> None:
    cfg = ModelConfig(
        name="anthropic",
        provider="anthropic",
        base_url="https://api.anthropic.com/v1",
        model="claude-sonnet-4-5-20250929",
    )
    caps = profile_capability_map(cfg)
    assert caps["chat"] is True
    assert caps["tools"] is True
    assert caps["batch"] is True
    assert caps["video_gen"] is False
    assert caps["tts"] is False


def test_openai_codex_profile_capabilities_support_chat_tools_and_streaming() -> None:
    cfg = ModelConfig(
        name="chatgpt",
        provider="openai_codex",
        base_url="https://chatgpt.com/backend-api/codex",
        model="gpt-5.5",
    )
    caps = profile_capability_map(cfg)
    assert caps["chat"] is True
    assert caps["tools"] is True
    assert caps["streaming"] is True
