"""Open a saved Build in Chromium and read the reply alongside its report card."""

import json

from tests.web_fixtures.thomas_chat_fixture import open_shell

BUILD_ID = "clarity-build"
ANSWER = "DONE: Built it.\n\nNEXT: Try it.\n\nTITLE: Build clarity\n\nVerification: 2/2 checks passed.\nUnchecked (no evidence either way):\n- Visit the page."


def test_saved_build_opens_immediately_and_shows_one_truthful_result():
    with open_shell() as shell:
        page = shell.page
        pending = []
        page.route(
            "**/api/evolve/agent/conversations",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"conversations": [{"id": BUILD_ID, "title": "Clarity build", "turn_count": 1}]}),
            ),
        )
        page.route("**/api/evolve/agent/conversations/" + BUILD_ID, lambda route: pending.append(route))
        page.click('.tc-mode-button[data-thomas-mode="code"]')
        page.wait_for_selector('iframe.bt-doc.is-active.is-ready[src*="tab_mode=code"]', timeout=20000)
        frame = next(f for f in shell.docs() if "tab_mode=code" in f.url)
        frame.wait_for_selector('button[data-history-id="' + BUILD_ID + '"]', timeout=20000)
        frame.click('button[data-history-id="' + BUILD_ID + '"]')
        frame.wait_for_selector('#tc-code-turns [role="status"]', timeout=10000)
        assert "Opening build…" in frame.locator('#tc-code-turns [role="status"]').inner_text()
        assert "Opening" in frame.locator(".tc-code-context").inner_text()
        assert "Ready" not in frame.locator(".tc-code-context").inner_text()
        assert "What should we make?" not in frame.locator(".tc-code-transcript").inner_text()
        assert len(pending) == 1, "the saved build request should still be waiting"
        # Hold the response longer than the old empty-page delay, not just one render tick.
        page.wait_for_timeout(3000)
        assert "Opening build…" in frame.locator('#tc-code-turns [role="status"]').inner_text()

        pending.pop().fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "conversation": {
                        "id": BUILD_ID,
                        "title": "Clarity build",
                        "turns": [
                            {
                                "role": "assistant",
                                "ok": False,
                                "transcript": json.dumps({"fc": "final", "text": ANSWER}),
                                "report": {
                                    "validations": [
                                        {"label": "First check", "passed": True},
                                        {"label": "Second check", "passed": False},
                                    ]
                                },
                            }
                        ],
                    },
                }
            ),
        )
        frame.wait_for_selector(".tc-code-reply", timeout=10000)
        reply = frame.locator(".tc-code-reply").first.inner_text()
        card = frame.locator(".tc-code-run-report").inner_text()
        assert "Built it." in reply
        assert "Try it." in reply
        for label in ("DONE:", "NEXT:", "TITLE:", "Verification:", "Unchecked (no evidence either way):"):
            assert label not in reply
        assert "2/2 checks passed" not in frame.locator(".tc-code-transcript").inner_text()
        assert "Some checks failed" in card
        assert "1/2 checks passed" in " ".join(card.split())
        assert not shell.errors, shell.errors


def test_new_build_dismisses_opening_message_from_slow_saved_build():
    with open_shell() as shell:
        page = shell.page
        pending = []
        page.route(
            "**/api/evolve/agent/conversations",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"conversations": [{"id": BUILD_ID, "title": "Clarity build", "turn_count": 1}]}),
            ),
        )
        page.route("**/api/evolve/agent/conversations/" + BUILD_ID, lambda route: pending.append(route))
        page.route(
            "**/api/evolve/agent/conversations/fresh-build/tree",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps({"ok": True, "entries": [], "path": ""})
            ),
        )
        page.route(
            "**/api/evolve/agent/conversations/new",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "conversation": {"id": "fresh-build", "turns": []}}),
            ),
        )
        page.click('.tc-mode-button[data-thomas-mode="code"]')
        page.wait_for_selector('iframe.bt-doc.is-active.is-ready[src*="tab_mode=code"]', timeout=20000)
        frame = next(f for f in shell.docs() if "tab_mode=code" in f.url)
        frame.wait_for_selector('button[data-history-id="' + BUILD_ID + '"]', timeout=20000)
        frame.click('button[data-history-id="' + BUILD_ID + '"]')
        frame.wait_for_selector('#tc-code-turns [role="status"]', timeout=10000)
        assert "Opening build…" in frame.locator(".tc-code-transcript").inner_text()
        frame.click("#tc-newchat")
        frame.wait_for_function("() => Boolean(document.querySelector('.tc-code-transcript [data-code-home]'))")
        assert "Opening build…" not in frame.locator(".tc-code-transcript").inner_text()
        pending.pop().fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "conversation": {"id": BUILD_ID, "turns": []}}),
        )
        frame.wait_for_timeout(300)
        assert "Opening build…" not in frame.locator(".tc-code-transcript").inner_text()
        assert frame.locator(".tc-code-transcript [data-code-home]").count() == 1, "the empty Build shows its slideshow"
        assert not shell.errors, shell.errors


def test_reopened_running_build_shows_its_durable_result_when_stream_finishes():
    with open_shell() as shell:
        page = shell.page
        run_id = "live-build-run"
        finished = False
        streams = []
        page.route(
            "**/api/evolve/agent/conversations",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"conversations": [{"id": BUILD_ID, "title": "Live build", "turn_count": 1}]}),
            ),
        )

        def conversation(route):
            turns = [{"role": "user", "text": "Build a clock"}]
            if finished:
                turns.append(
                    {
                        "role": "agent",
                        "run_id": run_id,
                        "ok": True,
                        "transcript": json.dumps({"fc": "final", "text": "The clock is ready."}),
                    }
                )
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "conversation": {"id": BUILD_ID, "title": "Live build", "turns": turns}}),
            )

        page.route("**/api/evolve/agent/conversations/" + BUILD_ID, conversation)
        page.route(
            "**/api/evolve/agent/conversations/" + BUILD_ID + "/tree",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps({"ok": True, "entries": []})
            ),
        )
        page.route(
            "**/api/evolve/agent/status?conversation_id=" + BUILD_ID,
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "running": True, "run_id": run_id}),
            ),
        )
        page.route("**/api/evolve/agent/stream?run_id=" + run_id, lambda route: streams.append(route))
        page.click('.tc-mode-button[data-thomas-mode="code"]')
        page.wait_for_selector('iframe.bt-doc.is-active.is-ready[src*="tab_mode=code"]', timeout=20000)
        frame = next(f for f in shell.docs() if "tab_mode=code" in f.url)
        frame.wait_for_selector('button[data-history-id="' + BUILD_ID + '"]', timeout=20000)
        frame.click('button[data-history-id="' + BUILD_ID + '"]')
        frame.wait_for_function("() => document.querySelector('.tc-code-context')?.textContent.includes('Working')")
        frame.wait_for_timeout(500)
        assert streams, "reopening a running build should follow its event stream"
        finished = True
        streams.pop().fulfill(
            status=200,
            content_type="text/event-stream",
            body="data: "
            + json.dumps({"type": "done", "run_id": run_id, "ok": True, "persistence_confirmed": True})
            + "\n\n",
        )
        frame.wait_for_function(
            "() => document.querySelector('.tc-code-reply')?.textContent.includes('The clock is ready.')"
        )
        frame.wait_for_timeout(300)
        assert "Completed" in frame.locator(".tc-code-context").inner_text()
        replies = frame.locator(".tc-code-reply").all_inner_texts()
        assert len(replies) == 1, f"durable answer should replace live one: {replies!r}"
        assert "durable history" not in frame.locator(".tc-code-transcript").inner_text()
        assert not shell.errors, shell.errors
