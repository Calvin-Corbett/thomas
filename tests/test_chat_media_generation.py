"""Drive the actual media controller through startup and observation failures."""

import subprocess
from pathlib import Path


def test_media_controller_lifecycle():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "node",
            str(root / "tests/web_node/chat_media_generation.mjs"),
            str(root / "thomas/server/web/js/chat_media_generation.js"),
            str(root / "thomas/server/web/chat.html"),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_create_menu_keeps_file_picker_pending_guard_media_delivery_and_stop():
    """Use the shipped page and real Chromium; only API replies are fixtures."""
    import base64
    import json
    import sys

    import pytest

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tests"))
    from web_fixtures.thomas_chat_fixture import browser_ok, open_shell

    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    with open_shell() as shell:
        page = shell.page
        uploads, submissions, cancellations = [], [], []
        job_state = {"state": "completed"}
        artifact = {
            "kind": "image",
            "name": "bus.png",
            "url": "/deliverable/media-fixture/bus.png",
        }

        def reply(route, body):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        def generate(route):
            submissions.append(route.request.post_data_json)
            reply(route, {"job_id": "media-fixture"})

        def cancel(route):
            cancellations.append(route.request.url)
            job_state["state"] = "cancelled"
            reply(route, {"ok": True, "cancelled": True, "state": "cancelled"})

        page.route("**/api/v2/chat/documents/extract", lambda route: uploads.append(route))
        page.route(
            "**/api/media/lanes",
            lambda route: reply(route, {"lanes": {"image": {"configured": True}}}),
        )
        page.route("**/api/media/generate", generate)
        page.route(
            "**/api/media/jobs/media-fixture",
            lambda route: reply(
                route,
                {
                    "job": {
                        "state": job_state["state"],
                        "deliverable": artifact,
                        "progress_text": "Drawing the bus",
                    }
                },
            ),
        )
        page.route(
            "**/delegations/media-fixture/announce",
            lambda route: reply(
                route,
                {
                    "ok": True,
                    "message": "Your bus image is ready.",
                    "artifacts": [artifact],
                },
            ),
        )
        page.route("**/delegations/media-fixture/cancel", cancel)
        page.route(
            "**/deliverable/media-fixture/bus.png",
            lambda route: route.fulfill(
                status=200,
                content_type="image/png",
                body=base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWZkAAAAASUVORK5CYII="
                ),
            ),
        )

        assert not shell.errors, shell.errors
        page.click("#tc-attach-btn")
        assert page.locator("#tc-create-menu").is_visible()
        with page.expect_file_chooser() as chooser:
            page.click("#tc-create-add-files")
        chooser.value.set_files({"name": "note.txt", "mimeType": "text/plain", "buffer": b"Orange buses"})
        page.wait_for_function("() => document.getElementById('tc-attach-row').textContent.includes('Reading')")
        assert page.locator("#tc-send").is_disabled()
        page.fill("#tc-input", "An orange bus")
        page.click("#tc-attach-btn")
        page.click("[data-create-action=image]")
        assert not submissions
        reply(
            uploads.pop(),
            {"ok": True, "document": {"name": "note.txt", "text": "Orange buses"}},
        )
        page.wait_for_function("() => !document.getElementById('tc-send').disabled")
        page.click("#tc-attach-btn")
        page.click("[data-create-action=image]")
        page.wait_for_selector("#tc-thread .tc-media-deliverable img")
        assert submissions[0]["session_id"] == "chat-a"
        assert submissions[0]["prompt"] == "An orange bus"
        assert page.locator("#tc-input").input_value() == ""
        assert page.locator("#tc-create-menu").is_hidden()
        assert page.locator("#tc-thread .tc-media-deliverable a").get_attribute("href").endswith("download=1")

        job_state["state"] = "running"
        page.fill("#tc-input", "A second orange bus")
        page.click("#tc-attach-btn")
        page.click("[data-create-action=image]")
        page.wait_for_function("() => document.getElementById('tc-send-icon').classList.contains('ph-stop')")
        page.click("#tc-send")
        page.wait_for_function("() => !document.getElementById('tc-send-icon').classList.contains('ph-stop')")
        assert len(cancellations) == 1
        assert len(submissions) == 2
        assert not shell.errors, shell.errors


def test_create_menu_and_setup_belong_to_selected_conversation():
    """Late startup/setup callbacks must not arm or write into a different chat."""
    import json
    import sys

    import pytest

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tests"))
    from web_fixtures.thomas_chat_fixture import browser_ok, open_shell

    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    with open_shell() as shell:
        page = shell.page
        # Standalone Chat lets the same document select another conversation;
        # the browser shell deliberately gives each tab its own live document.
        page.goto(shell.fixture.url + "/?browser=0", wait_until="load")
        page.wait_for_selector('[data-history-id="chat-b"]')
        assert not shell.errors, shell.errors
        pending, posts = [], []
        page.route("**/api/media/generate", lambda route: posts.append(route))
        page.click("#tc-attach-btn")
        page.click("[data-create-action=image]")
        assert page.locator("#tc-media-lane-chip").is_visible()
        page.click('[data-history-id="chat-b"]')
        assert page.locator("#tc-media-lane-chip").is_hidden()

        page.route("**/api/media/lanes", lambda route: pending.append(route))
        page.fill("#tc-input", "A picture for Beta")
        with page.expect_request("**/api/media/lanes"):
            page.click("#tc-attach-btn")
            page.click("[data-create-action=image]")
        page.click('[data-history-id="chat-c"]')
        pending.pop().fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"lanes": {"image": {"configured": True}}}),
        )
        page.wait_for_function("() => !document.getElementById('tc-thread').textContent.includes('Beta answer')")
        assert "Old preflight failed" not in page.locator("#tc-thread").inner_text()
        assert not posts

        page.unroute("**/api/media/lanes")
        page.route(
            "**/api/media/lanes",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"lanes": {}}),
            ),
        )
        page.route("**/api/media/lanes/image", lambda route: pending.append(route))
        page.fill("#tc-input", "A picture for Gamma")
        page.click("#tc-attach-btn")
        page.click("[data-create-action=image]")
        page.wait_for_selector("#tc-media-setup:not([hidden])")
        with page.expect_request("**/api/media/lanes/image"):
            page.click("[data-media-provider=local]")
        page.keyboard.press("Escape")
        page.click('[data-history-id="chat-b"]')
        assert page.locator("#tc-media-setup").is_hidden()
        with page.expect_response("**/api/media/lanes/image"):
            pending.pop().fulfill(status=200, content_type="application/json", body='{"configured":true}')
        assert page.locator("#tc-media-lane-chip").is_hidden()
        assert "is ready for Create image" not in page.locator("#tc-thread").inner_text()
        assert not posts
        assert not shell.errors, shell.errors
