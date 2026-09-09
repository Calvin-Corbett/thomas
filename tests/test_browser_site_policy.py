"""Sensitive sites: Thomas does not click or type there on its own.

Frontier parity (Claude in Chrome, Atlas agent mode): the agent pauses on
banking, payment, health and government sites so the person can act or watch.
Thomas's own bookmark bar carries a bank next to Gmail; the browser tools had
no such pause.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from thomas.tools import browser as browser_tools
from thomas.tools.site_policy import (
    SitePolicy,
    configure_site_policy,
    current_site_policy,
    sensitive_action_verdict,
)


def test_default_policy_knows_banks_and_leaves_ordinary_sites_alone() -> None:
    policy = SitePolicy()
    assert policy.is_sensitive("https://www.wellsfargo.com/login") is True
    assert policy.is_sensitive("https://connect.secure.wellsfargo.com/x") is True
    assert policy.is_sensitive("https://example.com/") is False


def test_user_added_hosts_count_and_match_subdomains() -> None:
    policy = SitePolicy(extra_hosts=["payroll.mycompany.com"])
    assert policy.is_sensitive("https://payroll.mycompany.com/run") is True
    assert policy.is_sensitive("https://app.payroll.mycompany.com/run") is True
    assert policy.is_sensitive("https://mycompany.com/") is False


def test_pause_verdict_names_the_host_and_how_to_proceed() -> None:
    policy = SitePolicy(mode="pause")
    verdict = sensitive_action_verdict("https://www.wellsfargo.com/transfer", action="click", policy=policy)
    assert verdict is not None
    assert "wellsfargo.com" in verdict
    assert "click" in verdict
    assert "sensitive" in verdict
    assert sensitive_action_verdict("https://example.com/", action="click", policy=policy) is None
    assert (
        sensitive_action_verdict("https://www.wellsfargo.com/", action="click", policy=SitePolicy(mode="allow")) is None
    )


def test_configure_replaces_the_process_policy() -> None:
    configure_site_policy(extra_hosts=["intranet.example"], mode="pause")
    try:
        assert current_site_policy().is_sensitive("https://intranet.example/") is True
    finally:
        configure_site_policy(extra_hosts=[], mode="pause")
    assert current_site_policy().is_sensitive("https://intranet.example/") is False


def test_browser_click_on_a_sensitive_page_pauses_without_clicking(monkeypatch) -> None:
    from thomas.tools.base import Tool, ToolResult
    from thomas.tools.browser_parity import SensitiveSiteGuard

    clicked: list[str] = []

    class _Inner(Tool):
        name = "browser.click"
        category = "browser"
        description = "fake"
        parameters = {"type": "object", "properties": {}}

        async def execute(self, args):  # noqa: ANN001, ARG002
            clicked.append("click")
            return ToolResult(ok=True, data="clicked")

    class _Page:
        url = "https://www.wellsfargo.com/account"

    sess = SimpleNamespace(page=_Page())

    async def _fake_ensure(_name, **_kw):
        return sess, sess.page

    monkeypatch.setattr(browser_tools, "_ensure_session_page", _fake_ensure)
    configure_site_policy(extra_hosts=[], mode="pause")

    result = asyncio.run(SensitiveSiteGuard(_Inner(), "click").execute({"selector": "text=Transfer"}))

    assert result.ok is False
    assert "wellsfargo.com" in str(result.error)
    assert clicked == []

    configure_site_policy(extra_hosts=[], mode="allow")
    allowed = asyncio.run(SensitiveSiteGuard(_Inner(), "click").execute({"selector": "text=Transfer"}))
    configure_site_policy(extra_hosts=[], mode="pause")
    assert allowed.ok is True and clicked == ["click"]


# ── The setting reaches the tools: preferences -> runtime policy -> site policy ──


def test_tools_preferences_carry_sensitive_site_fields_with_pause_default() -> None:
    from thomas.preferences._prefs import AdvancedToolsPrefs

    prefs = AdvancedToolsPrefs()
    assert prefs.browser_sensitive_hosts == ""
    assert prefs.browser_sensitive_mode == "pause"
    assert AdvancedToolsPrefs(browser_sensitive_mode="ALLOW ").browser_sensitive_mode == "allow"
    assert AdvancedToolsPrefs(browser_sensitive_mode="nonsense").browser_sensitive_mode == "pause"


def test_resolving_the_chat_runtime_policy_installs_the_saved_site_policy(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace as NS

    from thomas.core.config import AppConfig, ModelConfig, ToolsConfig
    from thomas.preferences.store import PreferencesPatch, PreferencesStore
    from thomas.server.chat_runtime_policy import resolve_chat_runtime_policy

    db_path = tmp_path / "preferences.sqlite"
    monkeypatch.setenv("THOMAS_DB_PATH", str(db_path))
    PreferencesStore(str(db_path)).patch(
        PreferencesPatch.model_validate(
            {
                "advanced": {
                    "tools": {
                        "browser_sensitive_hosts": "payroll.example, hr.example",
                        "browser_sensitive_mode": "pause",
                    }
                }
            }
        ),
        user_id="default",
        thread_id="session-1",
    )
    config = AppConfig(
        models={
            "local": ModelConfig(
                name="local", provider="openai_compat", base_url="http://127.0.0.1:11434/v1", model="m"
            )
        },
        default_model="local",
        tools=ToolsConfig(sandbox_root=str(tmp_path)),
    )
    configure_site_policy(extra_hosts=[], mode="allow")

    resolve_chat_runtime_policy(
        payload={},
        session_meta=NS(profile="", model_id=None, autonomy_level=2, system_prompt=None),
        saved_meta=None,
        config=config,
        session_id="session-1",
    )

    policy = current_site_policy()
    assert policy.mode == "pause"
    assert policy.is_sensitive("https://hr.example/") is True
    assert policy.is_sensitive("https://www.wellsfargo.com/") is True
