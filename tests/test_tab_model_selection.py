"""The browser bar's visible model is the model sent by its child documents."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import STUBS, browser_ok, open_shell  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def test_selection_bridge_rejects_unavailable_models_and_keeps_boot_choice():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the model-selection bridge check")
    result = subprocess.run(
        [
            node,
            str(REPO / "tests/web_node/tab_model_selection.mjs"),
            str(REPO / "thomas/server/web/chat.html"),
            str(REPO / "thomas/server/web/js/chat_model_selection.js"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")
def test_global_model_controls_loaded_and_late_child_chat_requests(monkeypatch):
    models = {
        "profiles": [
            {
                "name": "local",
                "provider": "local",
                "has_api_key": True,
                "models": [
                    {
                        "id": "fixture-1",
                        "display_name": "Fixture One",
                        "available": True,
                    },
                    {
                        "id": "fixture-2",
                        "display_name": "Fixture Two",
                        "available": True,
                    },
                ],
            }
        ],
        "preferences": {"active_profile": "local", "model_id": "fixture-1"},
        "default": "local",
    }
    monkeypatch.setitem(STUBS, "/api/models", models)
    with open_shell() as shell:
        page = shell.page
        page.click('#tc-chats [data-history-title="Beta"]', modifiers=["Control"])  # asks for a tab of its own
        page.wait_for_function("() => document.querySelector('iframe.bt-doc.is-ready')")
        child = shell.docs()[0]
        child.wait_for_function("() => document.getElementById('tc-thread').childElementCount > 0")
        page.click("#tc-model-btn")
        page.locator("#tc-model-options button").filter(has_text="Fixture Two").click()
        with page.expect_request(
            lambda request: request.method == "POST" and request.url.endswith("/api/v2/chat")
        ) as sent:
            child.fill("#tc-input", "Check my selected model")
            child.press("#tc-input", "Enter")
        assert sent.value.post_data_json["model_id"] == "fixture-2"
        assert sent.value.post_data_json["model"] == "local"
        assert page.locator("[data-model-switch]").is_visible()
        assert not child.locator("[data-model-switch]").is_visible()
        assert child.evaluate("() => ThomasModelSelection.current()") == {
            "profile": "local",
            "modelId": "fixture-2",
        }
        assert len([r for r in shell.fixture.requests if r == ("PATCH", "/api/preferences")]) == 1
        child.wait_for_function(
            "() => !document.querySelector('[data-thomas-mode=chat]').hasAttribute('data-running')",
            timeout=15000,
        )

        # The fixture always returns stale saved preferences. A newly opened
        # document must inherit the current browser choice after that response.
        page.click(".bt-tab.is-pinned")
        page.click('#tc-chats [data-history-title="Gamma"]', modifiers=["Control"])  # asks for a tab of its own
        page.wait_for_function("() => document.querySelectorAll('iframe.bt-doc.is-ready').length === 2")
        late = shell.docs()[1]
        late.wait_for_function("() => document.getElementById('tc-thread').childElementCount > 0")
        with page.expect_request(
            lambda request: request.method == "POST" and request.url.endswith("/api/v2/chat")
        ) as sent_late:
            late.fill("#tc-input", "Keep the model on a new tab")
            late.press("#tc-input", "Enter")
        assert sent_late.value.post_data_json["model_id"] == "fixture-2"
        assert len([r for r in shell.fixture.requests if r == ("PATCH", "/api/preferences")]) == 1
        late.wait_for_function(
            "() => !document.querySelector('[data-thomas-mode=chat]').hasAttribute('data-running')",
            timeout=15000,
        )
        assert not shell.errors, json.dumps(shell.errors)


@pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")
def test_stale_child_catalog_blocks_chat_and_build_until_selection_matches(monkeypatch):
    models = {
        "profiles": [
            {
                "name": "openai_codex",
                "provider": "openai_codex",
                "has_api_key": True,
                "models": [
                    {
                        "id": "gpt-fixture-1",
                        "display_name": "Fixture One",
                        "available": True,
                    },
                    {
                        "id": "gpt-fixture-2",
                        "display_name": "Fixture Two",
                        "available": True,
                    },
                ],
            }
        ],
        "preferences": {"active_profile": "openai_codex", "model_id": "gpt-fixture-1"},
        "default": "openai_codex",
    }
    monkeypatch.setitem(STUBS, "/api/models", models)
    with open_shell() as shell:
        page = shell.page
        page.add_init_script("""if (window.parent !== window) {
          const originalFetch = window.fetch;
          window.fetch = async (...args) => {
            const response = await originalFetch(...args);
            if (String(args[0]) !== '/api/models') return response;
            const body = await response.json();
            body.profiles[0].models = body.profiles[0].models.filter(model => model.id === 'gpt-fixture-1');
            return new Response(JSON.stringify(body), {headers: {'Content-Type':'application/json'}});
          };
        }""")
        posted = []
        page.on(
            "request",
            lambda request: (
                posted.append(request)
                if request.method == "POST" and request.url.endswith(("/api/v2/chat", "/api/evolve/agent/send"))
                else None
            ),
        )
        page.click('#tc-chats [data-history-title="Beta"]', modifiers=["Control"])  # asks for a tab of its own
        page.wait_for_function("() => document.querySelector('iframe.bt-doc.is-ready')")
        child = shell.docs()[0]
        child.wait_for_function("() => ThomasModelSelection.current().modelId === 'gpt-fixture-1'")
        page.click("#tc-model-btn")
        page.locator("#tc-model-options button").filter(has_text="Fixture Two").click()

        child.fill("#tc-input", "Keep this chat draft")
        child.press("#tc-input", "Enter")
        page.wait_for_timeout(200)
        assert not posted
        assert child.input_value("#tc-input") == "Keep this chat draft"
        assert "selected model is not ready" in child.eval_on_selector("#tc-input", "input => input.validationMessage")

        child.click('[data-thomas-mode="code"]')
        page.wait_for_function("() => document.querySelectorAll('iframe.bt-doc.is-ready').length === 2")
        build = next(frame for frame in shell.docs() if "tab_mode=code" in frame.url)
        build.wait_for_function("() => ThomasModelSelection.current().modelId === 'gpt-fixture-1'")
        build.fill("#tc-input", "Keep this build draft")
        build.press("#tc-input", "Enter")
        page.wait_for_timeout(200)
        assert not posted
        assert build.input_value("#tc-input") == "Keep this build draft"
        assert "selected model is not ready" in build.eval_on_selector("#tc-input", "input => input.validationMessage")

        # Choosing a model actually available to this tab clears the error and
        # stamps that same choice into the real Build request.
        page.click("#tc-model-btn")
        page.locator("#tc-model-options button").filter(has_text="Fixture One").click()
        assert build.evaluate("() => ThomasModelSelection.current().modelId") == "gpt-fixture-1"
        assert build.evaluate("() => ThomasUnifiedModes.mode()") == "code"
        assert not shell.errors, shell.errors
        with page.expect_request(
            lambda request: request.method == "POST" and request.url.endswith("/api/evolve/agent/send"),
            timeout=5000,
        ) as resumed:
            build.press("#tc-input", "Enter")
        assert resumed.value.post_data_json["model_id"] == "gpt-fixture-1"
        assert resumed.value.post_data_json["model"] == "gpt-fixture-1"
