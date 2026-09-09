from thomas.marketplace.specialists import tools
from thomas.marketplace.specialists.tools import ToolSpecialist


def test_tool_specialist_description_avoids_stale_module_count() -> None:
    specialist = ToolSpecialist(config=None, llm=None, tools=None)

    text = "\n".join(
        part
        for part in (
            tools.__doc__,
            ToolSpecialist.__doc__,
            specialist.description,
        )
        if part
    )

    assert "132" not in text
    assert "registered" in text
