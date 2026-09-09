from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_easy_setup_recognizes_openai_codex_before_local() -> None:
    setup = (ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8")

    assert '"openai_codex"' in setup
    assert "Test-OpenAICodexTokenConfigured" in setup
    assert '"ChatGPT OAuth profile is ready."' in setup
    assert '$CurrentModel.Trim().ToLowerInvariant() -eq "openai_codex"' in setup
    assert '@("openai_codex", "codex", "local"' in setup


def test_run_ui_does_not_warn_for_openai_codex_api_key() -> None:
    run_ui = (ROOT / "scripts" / "run-ui.ps1").read_text(encoding="utf-8")

    openai_codex_guard = 'if ($defaultModel -eq "openai_codex")'
    api_key_warning = "WARNING: default_model '{0}' has no API key configured."
    assert openai_codex_guard in run_ui
    assert run_ui.index(openai_codex_guard) < run_ui.index(api_key_warning)
