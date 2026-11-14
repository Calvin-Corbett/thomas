"""A second model reads every Thomas change against its request before your card, and nothing unchecked reaches it.

Of the 24 changes Thomas made to himself from 2026-09-24 to 09-27, the check before the card passed every one that
landed, and 9 of them still carried a defect found later. An independent reader, done by hand in another session,
declined 24 of 28 first hand-ins: tests that fail on dev rewritten, changelog lines that were not true, a file made up
to satisfy a misread request, real bugs. Twice a change that reader had found not safe reached your card anyway.

Now Thomas starts the read-only reviewer against a frozen patch while checks run, and only applies its verdict after
the checks pass on those bytes. SAFE goes to your card and says so; NOT SAFE goes back to its team
with the findings, as a failed check does; a reviewer that cannot run (a usage limit, a sign-in gone) holds the change
rather than let it through, and it is tried again later without running the tests again.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import capacity_ledger, green_checkout, green_handoff, precard, thomas_project
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.precard import review, review_dial
from thomas.server.routes import evolve_agent_autopilot as ap

EXECUTION = "thomas-reviewed1"
REQUEST = "Make add() also accept floats, and say so in its docstring."
CHANGED = 'def add(a: float, b: float) -> float:\n    """Adds two numbers, floats too."""\n    return a + b\n'
FINDING = "pkg/adder.py:1 the docstring says floats work but nothing tests a float"


def _git(cwd: Path, *args: str) -> None:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args]
    subprocess.run(command, cwd=cwd, check=True, capture_output=True)


def test_web_paths_ignore_traversal_even_when_under_web_prefix() -> None:
    patch = "diff --git a/thomas/server/web/../../private.js b/thomas/server/web/../../private.js\n"
    assert review._web_paths(patch) == []


def test_deleted_web_asset_still_allows_post_change_browser_evidence(tmp_path: Path) -> None:
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        'web.playtest thomas/server/web/index.html (viewport 1280x720)\n1. observe "body" -> "chat loaded"\nerrors: none',
        encoding="utf-8",
    )
    assert "Browser session reports" in review._browser_evidence(tmp_path, ["thomas/server/web/js/removed.js"])


def test_deleted_web_asset_rejects_report_from_before_removal(tmp_path: Path) -> None:
    folder = tmp_path / "thomas/server/web/js"
    folder.mkdir(parents=True)
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        'web.playtest thomas/server/web/index.html (viewport 1280x720)\n1. observe "body" -> "chat loaded"\nerrors: none',
        encoding="utf-8",
    )
    os.utime(report, (1, 1))
    assert review._browser_evidence(tmp_path, ["thomas/server/web/js/removed.js"]).startswith("No web.playtest")


def test_web_paths_include_destination_of_rename() -> None:
    patch = "diff --git a/old/chat.js b/thomas/server/web/js/chat.js\n"
    assert review._web_paths(patch) == ["thomas/server/web/js/chat.js"]


def test_review_prompt_probes_failures_not_only_request_match() -> None:
    text = review.prompt(REQUEST, precard.Checked(precard.PASSED, "tests passed"))
    for risk in ("lost on reload", "concurrent operation race", "freeze the server", "removing the fix", "boot-only"):
        assert risk in text


def test_review_prompt_only_sends_back_real_defects_with_scenarios() -> None:
    text = review.prompt(REQUEST, precard.Checked(precard.PASSED, "tests passed"))
    assert "Send it back ONLY for a real defect" in text
    assert "concrete scenario showing what fails" in text
    assert "Put those smaller points in notes for the hand-in instead" in text
    assert '"notes": ["<optional nonblocking observation>"]' in text


def test_safe_review_notes_travel_with_hand_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(review.REVIEW_ENV, raising=False)
    checked = precard.Checked(precard.PASSED, "tests passed")
    reply = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": json.dumps({"verdict": "SAFE", "findings": [], "notes": ["A naming suggestion"]}),
        }
    )
    verdict = review.read_verdict(0, reply)
    assert verdict.safe and verdict.notes == "A naming suggestion"
    monkeypatch.setattr(review, "review_hand_in", lambda *_: verdict)
    line = review.second_look("notes-case", REQUEST, checked).line
    assert review.SAFE_LINE in line and "Nonblocking review notes: A naming suggestion" in line


def test_safe_review_cannot_hide_blocking_findings_in_hand_in() -> None:
    reply = _reply("SAFE", ["a blocking defect"])
    with pytest.raises(review.ReviewUnavailable, match="SAFE but also named blocking findings"):
        review.read_verdict(0, reply)


def _reply(verdict: str, findings: list[str], *, prose: str = "I read the change and the request.") -> str:
    """What `claude -p --output-format json` prints: one result object whose text ends in the verdict line."""
    text = f"{prose}\n{json.dumps({'verdict': verdict, 'findings': findings})}"
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text})


class Reviewer:
    """Stands in for the Claude CLI: records what it was given and answers from a list, one answer per run."""

    def __init__(self, *answers: tuple[int, str]) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], cwd: str, prompt: str, timeout: float) -> tuple[int, str]:
        self.calls.append({"argv": argv, "cwd": cwd, "prompt": prompt, "timeout": timeout})
        return self.answers.pop(0)


def test_web_change_without_browser_attempt_reaches_reviewer_with_missing_evidence(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewer = _reviewer(monkeypatch, (0, _reply("SAFE", [])))
    green = green_checkout.find_green(EXECUTION)
    assert green is not None
    web = green.work / "thomas/server/web/js"
    web.mkdir(parents=True)
    (web / "chat.js").write_text("console.log('chat')\n", encoding="utf-8")
    checked = precard.Checked(
        precard.PASSED,
        "tests passed",
        patch="diff --git a/thomas/server/web/js/chat.js b/thomas/server/web/js/chat.js\n",
    )
    result = review.second_look(EXECUTION, "Keep chat messages on reload", checked)
    assert review.SAFE_LINE in result.line
    assert "No web.playtest report" in result.line
    assert "No web.playtest report" in reviewer.calls[0]["prompt"]


@pytest.mark.parametrize("asset", ["apps/site/src/app/page.tsx", "apps/site/src/components/Chat.tsx"])
def test_site_ui_change_without_browser_attempt_reaches_reviewer_with_missing_evidence(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, asset: str
) -> None:
    reviewer = _reviewer(monkeypatch, (0, _reply("SAFE", [])))
    green = green_checkout.find_green(EXECUTION)
    assert green is not None
    page = green.work / asset
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("export default function Page() { return null }\n", encoding="utf-8")
    checked = precard.Checked(precard.PASSED, "tests passed", patch=f"diff --git a/{asset} b/{asset}\n")
    result = review.second_look(EXECUTION, "Keep chat messages on reload", checked)
    assert "No web.playtest report" in result.line
    assert "No web.playtest report" in reviewer.calls[0]["prompt"]


def test_web_report_is_evidence_not_automatic_approval(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    green = green_checkout.find_green(EXECUTION)
    assert green is not None
    web = green.work / "thomas/server/web/js"
    web.mkdir(parents=True)
    (web / "chat.js").write_text("console.log('chat')\n", encoding="utf-8")
    report = green.work / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        "web.playtest thomas/server/web/chat.html (viewport 1280x720)\n"
        '1. observe "body" -> "chat loaded"\nerrors: none',
        encoding="utf-8",
    )
    checked = precard.Checked(
        precard.PASSED,
        "tests passed",
        patch="diff --git a/thomas/server/web/js/chat.js b/thomas/server/web/js/chat.js\n",
    )
    reviewer = _reviewer(
        monkeypatch, (0, _reply("NOT_SAFE", ["chat.js: page booted, but reload persistence was not tested"]))
    )
    with pytest.raises(review.ChangeFailedReview, match="reload persistence"):
        review.second_look(EXECUTION, "Keep chat messages on reload", checked)
    assert 'observe "body" -> "chat loaded"' in reviewer.calls[0]["prompt"]


def test_page_boot_alone_is_not_browser_evidence(tmp_path: Path) -> None:
    web = tmp_path / "thomas/server/web/js/chat.js"
    web.parent.mkdir(parents=True)
    web.write_text("console.log('chat')", encoding="utf-8")
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        "web.playtest thomas/server/web/chat.html (viewport 1280x720)\nerrors: none",
        encoding="utf-8",
    )
    assert review._browser_evidence(tmp_path, ["thomas/server/web/js/chat.js"]).startswith("No web.playtest")
    report.write_text(
        "web.playtest thomas/server/web/chat.html (viewport 1280x720)\n"
        '1. observe "body" -> "chat loaded"\nerrors: none',
        encoding="utf-8",
    )
    assert "Browser session reports" in review._browser_evidence(tmp_path, ["thomas/server/web/js/chat.js"])


def test_offline_sandbox_notice_does_not_hide_successful_browser_evidence(tmp_path: Path) -> None:
    web = tmp_path / "thomas/server/web/js/chat.js"
    web.parent.mkdir(parents=True)
    web.write_text("console.log('chat')", encoding="utf-8")
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        "web.playtest thomas/server/web/index.html (viewport 1280x720)\n"
        '1. observe "body" -> "chat loaded"\n'
        "errors: none\n"
        "blocked by the offline sandbox (not an error of the page): 1 request(s): https://cdn.example.test/",
        encoding="utf-8",
    )
    assert "Browser session reports" in review._browser_evidence(tmp_path, ["thomas/server/web/js/chat.js"])


def test_offline_notice_does_not_mask_a_browser_error(tmp_path: Path) -> None:
    web = tmp_path / "thomas/server/web/js/chat.js"
    web.parent.mkdir(parents=True)
    web.write_text("console.log('chat')", encoding="utf-8")
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        "web.playtest thomas/server/web/index.html (viewport 1280x720)\n"
        '1. observe "body" -> "chat loaded"\n'
        "errors: 1 (listed above)\n"
        "blocked by the offline sandbox (not an error of the page): 1 request(s): https://cdn.example.test/",
        encoding="utf-8",
    )
    assert review._browser_evidence(tmp_path, ["thomas/server/web/js/chat.js"]).startswith("No web.playtest")


def test_unrelated_browser_page_is_not_evidence_for_a_web_change(tmp_path: Path) -> None:
    web = tmp_path / "thomas/server/web/js/chat.js"
    web.parent.mkdir(parents=True)
    web.write_text("console.log('chat')", encoding="utf-8")
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        'web.playtest unrelated/index.html (viewport 1280x720)\n1. observe "body" -> "ok"\nerrors: none',
        encoding="utf-8",
    )
    assert review._browser_evidence(tmp_path, ["thomas/server/web/js/chat.js"]).startswith("No web.playtest")


def test_loopback_server_page_on_nondefault_port_covers_server_ui(tmp_path: Path) -> None:
    web = tmp_path / "thomas/server/web/js/settings.js"
    web.parent.mkdir(parents=True)
    web.write_text("console.log('settings')", encoding="utf-8")
    report = (
        "web.playtest http://127.0.0.1:8977/settings (viewport 1280x720)\n"
        '1. observe "body" -> "settings loaded"\nerrors: none'
    )
    evidence = tmp_path / ".thomas/playtest/session/report.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(report, encoding="utf-8")
    assert "Browser session reports" in review._browser_evidence(tmp_path, ["thomas/server/web/js/settings.js"])
    assert not review._report_covers_web_path(report, "apps/site/src/app/page.tsx")
    assert not review._report_covers_web_path(
        report.replace("127.0.0.1", "example.com"), "thomas/server/web/js/settings.js"
    )


def test_nondefault_loopback_server_report_reaches_browser_evidence(tmp_path: Path) -> None:
    web = tmp_path / "thomas/server/web/js/settings.js"
    web.parent.mkdir(parents=True)
    web.write_text("console.log('settings')", encoding="utf-8")
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        "web.playtest http://localhost:8977/settings (viewport 1280x720)\n"
        '1. observe "body" -> "settings loaded"\nerrors: none',
        encoding="utf-8",
    )
    assert "settings loaded" in review._browser_evidence(tmp_path, ["thomas/server/web/js/settings.js"])


def test_site_root_browser_report_does_not_cover_server_ui() -> None:
    report = (
        'web.playtest http://localhost:3000/index.html (viewport 1280x720)\n1. observe "body" -> "ok"\nerrors: none'
    )
    assert review._report_covers_web_path(report, "apps/site/src/app/page.tsx")
    assert not review._report_covers_web_path(report, "thomas/server/web/js/chat.js")
    wrong_origin = (
        "web.playtest http://localhost:3000/thomas/server/web/index.html (viewport 1280x720)\n"
        '1. observe "body" -> "ok"\nerrors: none'
    )
    assert not review._report_covers_web_path(wrong_origin, "thomas/server/web/js/chat.js")


def test_each_changed_web_surface_needs_its_own_browser_report(tmp_path: Path) -> None:
    server = tmp_path / "thomas/server/web/js/chat.js"
    site = tmp_path / "apps/site/src/app/page.tsx"
    for asset in (server, site):
        asset.parent.mkdir(parents=True)
        asset.write_text("changed", encoding="utf-8")
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        'web.playtest thomas/server/web/index.html (viewport 1280x720)\n1. observe "body" -> "ok"\nerrors: none',
        encoding="utf-8",
    )
    paths = ["thomas/server/web/js/chat.js", "apps/site/src/app/page.tsx"]
    assert review._browser_evidence(tmp_path, paths).startswith("No web.playtest")
    site_report = tmp_path / ".thomas/playtest/site/report.txt"
    site_report.parent.mkdir(parents=True)
    site_report.write_text(
        'web.playtest http://localhost:3000/ (viewport 1280x720)\n1. observe "body" -> "ok"\nerrors: none',
        encoding="utf-8",
    )
    assert "Browser session reports" in review._browser_evidence(tmp_path, paths)


def test_offline_sandbox_footer_does_not_hide_successful_browser_evidence(tmp_path: Path) -> None:
    web = tmp_path / "thomas/server/web/js/chat.js"
    web.parent.mkdir(parents=True)
    web.write_text("console.log('chat')", encoding="utf-8")
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        "web.playtest thomas/server/web/index.html (viewport 1280x720)\n"
        '1. observe "body" -> "chat loaded"\n'
        "errors: none\n"
        "blocked by the offline sandbox (not an error of the page): 1 request(s): https://example.org/image",
        encoding="utf-8",
    )
    assert "Browser session reports" in review._browser_evidence(tmp_path, ["thomas/server/web/js/chat.js"])


def test_failed_browser_step_is_not_successful_evidence(tmp_path: Path) -> None:
    web = tmp_path / "thomas/server/web/js/chat.js"
    web.parent.mkdir(parents=True)
    web.write_text("console.log('chat')", encoding="utf-8")
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        "web.playtest thomas/server/web/chat.html (viewport 1280x720)\n"
        '1. observe "body" -> "chat loaded"\n'
        '2. click "Send" -> FAILED: button missing\nstopped at step 2; later steps did not run\nerrors: none',
        encoding="utf-8",
    )
    assert review._browser_evidence(tmp_path, ["thomas/server/web/js/chat.js"]).startswith("No web.playtest")


def test_page_error_is_not_successful_browser_evidence(tmp_path: Path) -> None:
    web = tmp_path / "thomas/server/web/js/chat.js"
    web.parent.mkdir(parents=True)
    web.write_text("console.log('chat')", encoding="utf-8")
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        "web.playtest thomas/server/web/index.html (viewport 1280x720)\n"
        '1. observe "body" -> "chat loaded"\n'
        "errors: Uncaught TypeError: cannot persist message",
        encoding="utf-8",
    )
    assert review._browser_evidence(tmp_path, ["thomas/server/web/js/chat.js"]).startswith("No web.playtest")


def test_failed_step_after_long_observation_is_not_browser_evidence(tmp_path: Path) -> None:
    web = tmp_path / "thomas/server/web/js/chat.js"
    web.parent.mkdir(parents=True)
    web.write_text("console.log('chat')", encoding="utf-8")
    report = tmp_path / ".thomas/playtest/session/report.txt"
    report.parent.mkdir(parents=True)
    report.write_text(
        "web.playtest thomas/server/web/index.html (viewport 1280x720)\n"
        + '1. observe "body" -> '
        + "loaded " * 900
        + '\n2. click "Send" -> FAILED: button missing\n'
        + "stopped at step 2; later steps did not run\nerrors: none",
        encoding="utf-8",
    )
    assert review._browser_evidence(tmp_path, ["thomas/server/web/js/chat.js"]).startswith("No web.playtest")


def test_older_relevant_report_survives_newer_unrelated_reports(tmp_path: Path) -> None:
    web = tmp_path / "thomas/server/web/js/chat.js"
    web.parent.mkdir(parents=True)
    web.write_text("console.log('chat')", encoding="utf-8")
    for index, target in enumerate(("thomas/server/web/index.html", "other.html", "other.html", "other.html")):
        report = tmp_path / f".thomas/playtest/session{index}/report.txt"
        report.parent.mkdir(parents=True)
        report.write_text(
            f'web.playtest {target} (viewport 1280x720)\n1. observe "body" -> "ok"\nerrors: none',
            encoding="utf-8",
        )
        os.utime(report, (web.stat().st_mtime + index + 1,) * 2)
    assert "Browser session reports" in review._browser_evidence(tmp_path, ["thomas/server/web/js/chat.js"])


@pytest.fixture(autouse=True)
def _own_turns_and_pause(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second looks take turns, and pause, in this test's own ledger folder: never the real catalog's. A pause made
    here records no issue."""
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(capacity_ledger, "POLL_S", 0.02)
    monkeypatch.setattr(review_dial, "notice", lambda *_a: None)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A repo on dev, a green with a finished change in it, and a check before the card that passes it."""
    blue, greens = tmp_path / "blue", tmp_path / "green"
    (blue / "pkg").mkdir(parents=True)
    (blue / "pkg" / "adder.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
    (blue / ".gitignore").write_text(".thomas/\n", encoding="utf-8")
    for args in (("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(blue, *args)
    for folder in (greens / "work", greens / "git"):  # a green root that exists gets no ACLs set
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(greens))
    monkeypatch.delenv(review.REVIEW_ENV, raising=False)  # the suite turns it off; these tests are about it
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    monkeypatch.setattr(green_handoff, "_end_processes", lambda green: None)  # no cage runner in a test
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: blue)
    catalog = tmp_path / "catalog"
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: catalog)
    green = green_checkout.create_green(blue=blue, execution_id=EXECUTION)
    (green.work / "pkg" / "adder.py").write_text(CHANGED, encoding="utf-8")
    checks: list[str] = []

    def passed(execution_id: str) -> precard.Checked:  # the check before the card, run for real elsewhere
        checks.append(execution_id)
        patch = green_checkout.green_patch(green_checkout.find_green(execution_id))
        line = "Checked against dev: it applies cleanly; 1 test file(s) ran, no failure this change causes."
        return precard.Checked(
            precard.PASSED,
            line,
            patch=patch,
            patch_sha256=precard.patch_sha256(patch),
            dev_tip=green_handoff.dev_tip(execution_id),
        )

    monkeypatch.setattr(precard, "check_for_hand_in", passed)
    record = {"execution_id": EXECUTION}
    cid = str(forge_code_store.new_conversation(green.work, title="floats", thomas_project=record)["id"])
    forge_code_store.append_user_turn(green.work, cid, REQUEST)
    forge_code_store.append_agent_turn(
        green.work, cid, model="gpt", transcript="", changed_files=["pkg/adder.py"], returncode=0,
        ok=True, noop=False, reason="1 file(s) changed", outcome="completed",
    )  # fmt: skip
    forge_code_projects.bind_conversation(
        catalog, cid, green.work, settings={"requested": {"autonomy_level": ap.AUTOPILOT}}, allow_without_history=True
    )
    return SimpleNamespace(tmp=tmp_path, green=green, catalog=catalog, cid=cid, checks=checks, starts=[])


def _reviewer(monkeypatch: pytest.MonkeyPatch, *answers: tuple[int, str]) -> Reviewer:
    reviewer = Reviewer(*answers)
    monkeypatch.setattr(review, "run_reviewer", reviewer)
    return reviewer


def _submissions(world: SimpleNamespace) -> list[str]:
    inbox = world.tmp / "inbox"
    return sorted(path.name for path in inbox.iterdir()) if inbox.is_dir() else []


def _app(world: SimpleNamespace) -> dict[Any, Any]:
    async def hook(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        world.starts.append(body)
        forge_code_store.append_user_turn(world.green.work, body["conversation_id"], body["message"])
        return 200, {"ok": True, "conversation_id": body["conversation_id"]}

    return {APP_PRAXIS_START_CODE_RUN: hook, APP_LOCAL_PORT: 8899}


def test_second_look_starts_before_the_check_finishes(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()
    original_check = precard.check_for_hand_in

    def checking(execution_id: str) -> precard.Checked:
        assert started.wait(5), "the second look must begin while the check is running"
        return original_check(execution_id)

    def reviewing(execution_id: str, request: str, patch: str) -> review.Verdict:
        assert REQUEST in request and '"""Adds two numbers, floats too."""' in patch
        started.set()
        return review.Verdict(safe=True)

    monkeypatch.setattr(precard, "check_for_hand_in", checking)
    monkeypatch.setattr(review, "review_verdict", reviewing)

    thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)

    assert world.checks == [EXECUTION]
    assert _submissions(world), "both independent checks must finish before the card"


def test_parallel_review_is_not_run_twice_when_disabled(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    monkeypatch.setattr(review, "review_verdict", lambda *args: calls.append(args) or None)
    monkeypatch.setattr(review, "second_look", lambda *args: pytest.fail("do not run a second review"))

    submission = thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)

    assert submission is not None and len(calls) == 1


def test_the_reviewer_can_only_read_and_is_given_the_request_the_change_and_check_context(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewer = _reviewer(monkeypatch, (0, _reply("SAFE", [])))

    thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)

    [call] = reviewer.calls
    # One plain ChatGPT call with no tools (2026-10-25: "make it all chat gpt for the review too"): the call names
    # only the model and effort, so nothing it is shown can make it run or change anything.
    assert call["argv"] == ["chatgpt", review.DEFAULT_MODEL, "high"], call["argv"]
    assert Path(call["cwd"]) == world.green.work, "its files come from the team's own copy, where the change is"
    assert REQUEST in call["prompt"]
    assert '+    """Adds two numbers, floats too."""' in call["prompt"], "the change itself"
    assert "=== pkg/adder.py ===" in call["prompt"] and CHANGED in call["prompt"], "the changed file's full text"
    assert "You have no tools" in call["prompt"]
    assert "Checks are running in parallel" in call["prompt"], "the review must not pretend checks already passed"
    assert "do not assume it passed" in call["prompt"]
    assert "check has already run" not in call["prompt"]
    # A team bumped the version in pyproject.toml and thomas/__init__.py in a Work fix nobody asked to release, and
    # the reader's findings on it never mentioned that (2026-09-28): release metadata is named as out of scope.
    assert "pyproject.toml" in call["prompt"] and "release metadata" in call["prompt"]


def test_a_change_the_reviewer_finds_not_safe_goes_back_to_its_team(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reviewer(monkeypatch, (0, _reply("NOT_SAFE", [FINDING])))
    forge_code_projects.bind_conversation(
        world.catalog,
        world.cid,
        world.green.work,
        settings={"requested": {"autonomy_level": 3}},
        allow_without_history=True,
    )

    asyncio.run(ap._settle_thomas_project(world.green.work, world.catalog, world.cid, app=_app(world)))

    assert _submissions(world) == [], "nothing reached your card"
    conversation = forge_code_store.load_conversation(world.green.work, world.cid)
    round_one = (conversation.get("thomas_project") or {}).get("repairs")[0]
    assert (round_one["round"], round_one["why"]) == (1, thomas_project.SENT_BACK)
    assert FINDING in round_one["detail"]
    assert len(world.starts) == 1 and FINDING in world.starts[0]["message"]


def test_a_change_the_reviewer_finds_safe_reaches_your_card_saying_so(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reviewer(monkeypatch, (0, _reply("SAFE", [])))

    submission = thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)

    assert submission is not None and _submissions(world) == [f"self-{EXECUTION}"]
    line = json.loads((submission / "submission.json").read_text(encoding="utf-8"))["checked"]
    assert "no failure this change causes" in line and review.SAFE_LINE in line, line


@pytest.mark.parametrize(
    "answer",
    [
        (1, "Claude AI usage limit reached|1790600000"),  # the plan's limit
        (0, json.dumps({"type": "result", "is_error": True, "result": "Invalid API key · Please run /login"})),
        (0, _reply("MAYBE", [])),  # an answer with no verdict in it is no check at all
    ],
    ids=["usage limit", "signed out", "no verdict"],
)
def test_a_reviewer_that_cannot_run_holds_the_change_then_it_goes_without_the_tests_again(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, answer: tuple[int, str]
) -> None:
    reviewer = _reviewer(monkeypatch, answer, (0, _reply("SAFE", [])))

    with pytest.raises(review.ReviewUnavailable):
        thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)
    assert _submissions(world) == [], "held: never handed in unchecked"
    assert thomas_project.settled_record(world.catalog, world.cid) is None

    monkeypatch.setattr(review_dial, "clock", lambda: time.time() + 3 * 86400)  # the plan's reset has passed
    submission = thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)

    assert submission is not None and _submissions(world) == [f"self-{EXECUTION}"]
    assert world.checks == [EXECUTION], "the change had not moved, so its tests were not run again"
    assert len(reviewer.calls) == 2


def test_unexpected_parallel_review_error_holds_the_change(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object) -> None:
        raise RuntimeError("review process broke")

    monkeypatch.setattr(review, "review_verdict", broken)

    with pytest.raises(review.ReviewUnavailable, match="review process broke"):
        thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)

    assert _submissions(world) == []
    assert world.checks == [EXECUTION]


def test_a_held_change_is_tried_again_by_itself(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _reviewer(monkeypatch, (1, "Claude AI usage limit reached|1790600000"), (0, _reply("SAFE", [])))
    from thomas.server import autopilot_hold_tick, autopilot_restart, hand_in_hold

    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))

    async def settle_and_retry() -> None:
        app = _app(world)
        forge_code_projects.bind_conversation(
            world.catalog,
            world.cid,
            world.green.work,
            settings={"requested": {"autonomy_level": 3}},
            allow_without_history=True,
        )
        await ap._settle_thomas_project(world.green.work, world.catalog, world.cid, app=app)
        row = hand_in_hold.row(world.catalog, world.cid)
        assert row and row["state"] == "held" and row["tries"] == 1
        assert hand_in_hold.change(world.catalog, world.cid, row["gen"], {**row, "next_at": 0}, expected=row)
        monkeypatch.setattr(review_dial, "clock", lambda: time.time() + 3 * 86400)  # the plan's reset has passed
        assert await autopilot_hold_tick.tick(app, world.catalog) == [world.cid]
        for _ in range(500):
            if _submissions(world):
                return
            await asyncio.sleep(0.02)

    asyncio.run(settle_and_retry())

    assert _submissions(world) == [f"self-{EXECUTION}"]
    assert world.starts == [], "a hold is not a repair round"


def test_the_second_check_can_be_turned_off(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    reviewer = _reviewer(monkeypatch)
    monkeypatch.setenv(review.REVIEW_ENV, "off")

    submission = thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)

    assert submission is not None and reviewer.calls == []


def test_a_pause_that_begins_as_a_second_look_is_admitted_stops_it_before_the_cli(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviewer = _reviewer(monkeypatch, (0, _reply("SAFE", [])))
    asked = []

    def pause_begins_once_it_is_admitted(now: float) -> tuple[float, bool]:
        asked.append(now)  # however many times it is asked: no pause the first time, a pause every time after
        return (0.0, False) if len(asked) == 1 else (time.time() + 600, False)

    monkeypatch.setattr(review_dial, "_pause", pause_begins_once_it_is_admitted)

    with pytest.raises(review.UsageLimited):
        review.review_hand_in(EXECUTION, REQUEST, precard.Checked(precard.PASSED, "line"))

    assert reviewer.calls == [] and review_dial.running() == 0, "it never reached the CLI, and its place is given back"


def test_a_pause_that_cannot_be_kept_still_holds_the_second_look_that_met_the_limit(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reviewer(monkeypatch, (1, "Claude AI usage limit reached|1790600000"))

    def busy(_path: Path, _payload: Any) -> None:
        raise PermissionError("the pause file is busy")

    monkeypatch.setattr("thomas.core.atomic_json.write_json_atomic", busy)

    with pytest.raises(review.UsageLimited):
        review.review_hand_in(EXECUTION, REQUEST, precard.Checked(precard.PASSED, "line"))

    assert review_dial.pause_shown() is None, "nothing was kept, and the next second look asks the CLI itself"


def test_a_hand_in_that_meets_your_plans_limit_is_held_until_it_resets_without_a_strike(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests._claude_plan_fakes import SESSION_LIMIT
    from thomas.server import autopilot_hold_tick, autopilot_restart, hand_in_hold

    limit = json.dumps({"type": "result", "is_error": True, "api_error_status": 429, "result": SESSION_LIMIT})
    _reviewer(monkeypatch, (1, limit), (0, _reply("SAFE", [])))
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))

    async def settle_then_wait() -> None:
        app = _app(world)
        forge_code_projects.bind_conversation(  # below Autopilot the finished turn settles, as in the test above
            world.catalog,
            world.cid,
            world.green.work,
            settings={"requested": {"autonomy_level": 3}},
            allow_without_history=True,
        )
        await ap._settle_thomas_project(world.green.work, world.catalog, world.cid, app=app)
        row = hand_in_hold.row(world.catalog, world.cid)
        assert row and row["state"] == "held" and row["step"] == "second look" and row["strikes"] == 0
        shown = review_dial.pause_shown()
        assert shown is not None and row["next_at"] == shown[0]
        reset = shown[0]
        assert await autopilot_hold_tick.tick(app, world.catalog) == [], "nothing asks again before the reset"
        monkeypatch.setattr(review_dial, "clock", lambda: reset + 1)
        assert hand_in_hold.change(world.catalog, world.cid, row["gen"], {**row, "next_at": 0}, expected=row)
        assert await autopilot_hold_tick.tick(app, world.catalog) == [world.cid]
        for _ in range(500):
            if _submissions(world):
                return
            await asyncio.sleep(0.02)

    asyncio.run(settle_then_wait())

    assert _submissions(world) == [f"self-{EXECUTION}"] and world.checks == [EXECUTION], "the held check was reused"


def test_each_second_look_is_measured_and_one_with_no_verdict_is_recorded_as_raised(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("THOMAS_STEP_LOG_DIR", str(world.tmp / "metrics"))
    _reviewer(monkeypatch, (0, _reply("MAYBE", [])), (0, _reply("SAFE", [])))
    with pytest.raises(review.ReviewUnavailable):
        thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)
    monkeypatch.setattr(review_dial, "clock", lambda: time.time() + 3 * 86400)
    thomas_project.settle_if_finished(world.green.work, world.catalog, world.cid)
    rows = [
        json.loads(line) for path in (world.tmp / "metrics").glob("*.jsonl") for line in path.read_text().splitlines()
    ]
    looks = [row for row in rows if row["step"] == "second_look"]
    assert [(row["outcome"], row["exit"]) for row in looks] == [("raised ReviewUnavailable", 0), ("safe", 0)]
