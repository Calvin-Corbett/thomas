import json

import pytest

from thomas.browser.p007_browser_action_wait_conditions import (
    BrowserWaitFailureError,
    InvalidWaitConditionsError,
    execute_action_with_waits_async,
    plan_action_with_waits,
    plan_to_dict,
    spec_from_json,
)


class FakePage:
    def __init__(self):
        self.calls = []

    async def click(self, selector, **kwargs):
        self.calls.append(("click", selector, kwargs))

    async def goto(self, url, **kwargs):
        self.calls.append(("goto", url, kwargs))

    async def fill(self, selector, text, **kwargs):
        self.calls.append(("fill", selector, text, kwargs))

    async def wait_for_selector(self, selector, **kwargs):
        self.calls.append(("wait_for_selector", selector, kwargs))

    async def wait_for_load_state(self, state, **kwargs):
        self.calls.append(("wait_for_load_state", state, kwargs))

    async def wait_for_url(self, url, **kwargs):
        self.calls.append(("wait_for_url", url, kwargs))

    async def wait_for_timeout(self, ms, **kwargs):
        self.calls.append(("wait_for_timeout", ms, kwargs))


@pytest.mark.asyncio
async def test_plan_and_execute_click_with_waits():
    spec = spec_from_json(
        json.dumps(
            {
                "action": {"kind": "click", "selector": "#submit"},
                "waits": [
                    {"kind": "load_state", "state": "networkidle", "timeout_ms": 10000},
                    {"kind": "selector", "selector": "#done", "state": "visible"},
                    {"kind": "timeout", "timeout_ms": 250},
                ],
                "default_timeout_ms": 5000,
            }
        )
    )

    plan = plan_action_with_waits(spec)
    plan_dict = plan_to_dict(plan)

    assert plan_dict["action"]["method"] == "click"
    assert plan_dict["action"]["args"] == ["#submit"]
    assert [w["method"] for w in plan_dict["waits"]] == [
        "wait_for_load_state",
        "wait_for_selector",
        "wait_for_timeout",
    ]

    page = FakePage()
    await execute_action_with_waits_async(page, spec)

    # Action happens first, then waits in order.
    assert [c[0] for c in page.calls] == [
        "click",
        "wait_for_load_state",
        "wait_for_selector",
        "wait_for_timeout",
    ]


def test_default_timeout_applies_to_waits():
    spec = spec_from_json(
        json.dumps(
            {
                "action": {"kind": "click", "selector": "#submit"},
                "waits": [{"kind": "selector", "selector": "#done", "state": "visible"}],
                "default_timeout_ms": 1234,
            }
        )
    )
    plan = plan_to_dict(plan_action_with_waits(spec))
    assert plan["waits"][0]["kwargs"]["timeout"] == 1234


def test_invalid_wait_kind_is_deterministic():
    with pytest.raises(InvalidWaitConditionsError) as exc:
        spec_from_json(
            json.dumps(
                {
                    "action": {"kind": "click", "selector": "#submit"},
                    "waits": [{"kind": "banana", "timeout_ms": 10}],
                }
            )
        )
    assert "waits[0].kind" in str(exc.value)


def test_negative_timeout_is_invalid():
    with pytest.raises(InvalidWaitConditionsError) as exc:
        spec_from_json(
            json.dumps(
                {
                    "action": {"kind": "click", "selector": "#submit"},
                    "waits": [{"kind": "timeout", "timeout_ms": -1}],
                }
            )
        )
    assert ">= 0" in str(exc.value)


@pytest.mark.asyncio
async def test_external_failure_is_wrapped():
    class ExplodingPage(FakePage):
        async def wait_for_load_state(self, state, **kwargs):
            raise RuntimeError("driver-specific boom")

    spec = spec_from_json(
        json.dumps(
            {
                "action": {"kind": "click", "selector": "#submit"},
                "waits": [{"kind": "load_state", "state": "load"}],
            }
        )
    )

    with pytest.raises(BrowserWaitFailureError) as exc:
        await execute_action_with_waits_async(ExplodingPage(), spec)

    # Deterministic message (no driver exception text)
    assert str(exc.value) == "browser failed during wait[0]:wait_for_load_state"
