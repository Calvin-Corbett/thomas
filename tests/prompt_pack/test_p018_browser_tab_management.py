import json
import pytest

from thomas.browser.p018_browser_tab_management import (
    InMemoryTabBackend,
    InvalidTabRequestError,
    TabConfigError,
    TabManagementRequest,
    TabNotFoundError,
    coerce_tab_backend,
    manage_tabs,
)
from thomas.cli.commands.browser import p018_browser_tab_management as cli


def test_manage_tabs_happy_path_flow() -> None:
    backend = InMemoryTabBackend()

    r1 = manage_tabs(TabManagementRequest(action="open", url="https://example.com"), backend)
    assert r1.ok is True
    assert r1.action == "open"
    assert len(r1.tabs) == 1
    assert r1.tabs[0].active is True
    assert r1.affected_tab is not None
    assert r1.affected_tab.url == "https://example.com"

    r2 = manage_tabs(TabManagementRequest(action="open", url="https://openai.com", activate=False), backend)
    assert r2.ok is True
    assert len(r2.tabs) == 2
    assert r2.tabs[0].active is True
    assert r2.tabs[1].active is False

    r3 = manage_tabs(TabManagementRequest(action="activate", tab_index=1), backend)
    assert r3.ok is True
    assert len(r3.tabs) == 2
    assert r3.tabs[1].active is True

    r4 = manage_tabs(TabManagementRequest(action="close_others", tab_index=1), backend)
    assert r4.ok is True
    assert len(r4.tabs) == 1
    assert r4.tabs[0].active is True

    remaining_id = r4.tabs[0].id
    r5 = manage_tabs(TabManagementRequest(action="close", tab_id=remaining_id), backend)
    assert r5.ok is True
    assert r5.tabs == []


def test_manage_tabs_invalid_request_is_deterministic() -> None:
    backend = InMemoryTabBackend()

    with pytest.raises(InvalidTabRequestError) as exc:
        manage_tabs(TabManagementRequest(action="activate"), backend)  # missing target
    assert exc.value.code == "invalid_input"

    with pytest.raises(InvalidTabRequestError) as exc2:
        manage_tabs(TabManagementRequest(action="close", tab_id="x", tab_index=0), backend)  # ambiguous
    assert exc2.value.code == "invalid_input"


def test_manage_tabs_tab_not_found_is_deterministic() -> None:
    backend = InMemoryTabBackend()
    manage_tabs(TabManagementRequest(action="open", url="https://example.com"), backend)

    with pytest.raises(TabNotFoundError) as exc:
        manage_tabs(TabManagementRequest(action="activate", tab_index=99), backend)
    assert exc.value.code == "tab_not_found"


def test_coerce_backend_rejects_unsupported_object() -> None:
    class NotABackend:
        pass

    with pytest.raises(TabConfigError) as exc:
        coerce_tab_backend(NotABackend())
    assert exc.value.code == "missing_config"
    assert "does not support tab management" in exc.value.message.lower()


def test_coerce_backend_playwright_like_context_works() -> None:
    class DummyPage:
        def __init__(self, url: str) -> None:
            self.url = url
            self._closed = False
            self._front = False

        def goto(self, url: str) -> None:
            self.url = url

        def bring_to_front(self) -> None:
            self._front = True

        def close(self) -> None:
            self._closed = True

        def title(self) -> str:
            return "Dummy"

    class DummyContext:
        def __init__(self) -> None:
            self.pages = []

        def new_page(self) -> DummyPage:
            p = DummyPage("about:blank")
            self.pages.append(p)
            return p

    ctx = DummyContext()
    backend = coerce_tab_backend(ctx)

    r1 = manage_tabs(TabManagementRequest(action="open", url="https://example.com"), backend)
    assert r1.ok is True
    assert len(r1.tabs) == 1
    assert r1.tabs[0].url == "https://example.com"


def test_cli_json_success_and_failure(capsys: pytest.CaptureFixture[str]) -> None:
    backend = InMemoryTabBackend()

    # Success
    exit_code = cli.main(["tabs", "--json", "open", "--url", "https://example.com"], backend=backend)
    assert exit_code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["action"] == "open"
    assert len(payload["tabs"]) == 1

    # Failure: missing backend config
    exit_code = cli.main(["tabs", "--json", "list"], backend=None)
    assert exit_code == 2
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"

    # Failure: invalid input (no target)
    exit_code = cli.main(["tabs", "--json", "activate"], backend=backend)
    assert exit_code == 2
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
