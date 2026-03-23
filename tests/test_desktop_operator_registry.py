import asyncio

from thomas.desktop_operator.tools import register_desktop_operator_tools
from thomas.tools.registry import ToolRegistry


def test_desktop_operator_tools_register_under_desktop_category() -> None:
    registry = ToolRegistry()
    register_desktop_operator_tools(registry)

    desktop_tools = registry.list_tools(category="desktop")
    names = {tool.name for tool in desktop_tools}
    assert "desktop.start_session" in names
    assert "desktop.pause_session" in names
    assert "desktop.resume_session" in names
    assert "desktop.terminate_session" in names
    assert "desktop.get_risk_state" in names
    assert "desktop.list_apps" in names
    assert "desktop.bind_app" in names
    assert "desktop.act" in names
    assert "desktop.verify" in names
    assert "desktop.end_session" in names

    async def run() -> None:
        result = await registry.execute("desktop.list_apps", {})
        assert result.ok is True or result.ok is False

    asyncio.run(run())
