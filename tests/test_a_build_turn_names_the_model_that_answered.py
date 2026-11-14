"""A Build turn must name the model that answered, not the name it asked for.

``thomas/models/sources/claude_cli.py`` labelled Claude Code's ``opus`` "Claude
Opus (newest)". Nobody had checked it. The CLI resolves that name privately and
prints the answer in its ``system``/``init`` event, and Thomas threw the event
away — so a turn stored ``claude:opus`` and the exact model was unrecoverable
forever after. Every project that ran overnight is labelled with an alias and a
superlative, and no record anywhere can say which Opus produced any of it.

The transcript lines asserted on below are the REAL ones, captured from Claude
Code 2.1.282 on this machine on 2026-09-25 by running::

    claude -p --model opus --output-format stream-json --input-format stream-json --verbose

which answered ``"model":"claude-opus-5-5"`` in its init event, in its assistant
messages, and as the single key of the result's ``modelUsage``. That is what
makes this file evidence rather than a guess about a payload shape.
"""

from __future__ import annotations

import json
import shutil

import pytest

from thomas.core import claude_alias_ids
from thomas.forge.anvil import forge_code_store
from thomas.forge.anvil.build_model_receipt import (
    MODEL_EVENT_KIND,
    RECEIPT_KEY,
    engine_model_from_transcript,
    engine_models_in_transcript,
    is_model_receipt,
)
from thomas.forge.anvil.forge_event_stream import ClaudeStreamTranslator

# Verbatim from the run above, trimmed to the keys under test.
INIT_LINE = json.dumps(
    {"type": "system", "subtype": "init", "session_id": "d001fe08", "model": "claude-opus-5-5", "tools": ["Read"]}
)
ASSISTANT_LINE = json.dumps(
    {
        "type": "assistant",
        "message": {"role": "assistant", "model": "claude-opus-5-5", "content": [{"type": "text", "text": "ok"}]},
    }
)
RESULT_LINE = json.dumps(
    {"type": "result", "is_error": False, "result": "ok", "modelUsage": {"claude-opus-5-5": {"inputTokens": 4}}}
)


@pytest.fixture(autouse=True)
def _nothing_observed_yet(tmp_path, monkeypatch):
    """Each test starts having observed nothing.

    Both halves are needed, and finding that out is the point: the resolutions
    are cached in the process AND written under ``THOMAS_HOME``, so clearing
    only the cache left the previous test's file on disk and the next test read
    it back. That persistence is the feature -- a machine should not forget
    which model its alias starts every time Thomas restarts -- so the test
    gives each case its own home rather than asking the module to be forgetful.
    """
    monkeypatch.setenv("THOMAS_HOME", str(tmp_path / "home"))
    claude_alias_ids.forget_observations()
    yield
    claude_alias_ids.forget_observations()


# --- what the engine said ------------------------------------------------------


def test_the_init_event_becomes_a_model_receipt_naming_the_exact_id() -> None:
    translate = ClaudeStreamTranslator()

    events = translate(INIT_LINE)

    assert [e["fc"] for e in events] == [MODEL_EVENT_KIND]
    assert is_model_receipt(events[0])
    assert events[0]["model"] == "claude-opus-5-5"
    assert events[0]["source"] == "init"
    # The Build view renders ``meta`` as a status line, live and on replay, so
    # this is the line a person sees -- not a bubble of the agent talking.
    assert MODEL_EVENT_KIND == "meta"
    assert events[0]["text"] == "Ran on claude-opus-5-5"


def test_an_ordinary_status_line_is_not_a_model_receipt() -> None:
    """The receipt shares ``meta`` with every build-status line; only it counts."""
    assert not is_model_receipt({"fc": "meta", "text": "dispatched via claude CLI (opus)"})
    assert not is_model_receipt({"fc": "meta", "model": "claude-opus-5-5", "text": "no receipt key"})
    assert engine_model_from_transcript(json.dumps({"fc": "meta", "model": "claude-opus-5", "text": "x"})) == ""


def test_the_same_model_repeated_all_run_is_recorded_once() -> None:
    translate = ClaudeStreamTranslator()

    first = translate(INIT_LINE)
    again = translate(ASSISTANT_LINE)
    terminal = translate(RESULT_LINE)

    assert [e["fc"] for e in first] == [MODEL_EVENT_KIND]
    # The assistant line still yields its text; it just does not re-announce the model.
    assert [e["fc"] for e in again] == ["say"]
    assert [e["fc"] for e in terminal] == ["final"]


def test_a_run_that_never_saw_an_init_still_learns_the_model_from_modelusage() -> None:
    """The terminal result names it too, so a stream joined late is not lost."""
    translate = ClaudeStreamTranslator()

    events = translate(RESULT_LINE)

    assert [e["fc"] for e in events] == [MODEL_EVENT_KIND, "final"]
    assert events[0]["model"] == "claude-opus-5-5"
    assert events[0]["source"] == "modelUsage"


def _receipt(model: str, source: str) -> str:
    return json.dumps({"fc": MODEL_EVENT_KIND, RECEIPT_KEY: "model", "model": model, "source": source})


def test_the_model_receipt_survives_a_stored_transcript() -> None:
    transcript = "\n".join(
        [
            json.dumps({"fc": "meta", "text": "starting"}),
            _receipt("claude-opus-5-5", "init"),
            "not json at all",
            json.dumps({"fc": "final", "text": "done"}),
        ]
    )

    assert engine_model_from_transcript(transcript) == "claude-opus-5-5"
    assert engine_models_in_transcript(transcript) == ["claude-opus-5-5"]
    assert engine_model_from_transcript("") == ""


def test_the_first_model_is_the_one_the_run_started_on() -> None:
    """A mid-run move to another model must not overwrite what answered first."""
    transcript = "\n".join(
        [
            _receipt("claude-opus-5-5", "init"),
            _receipt("claude-haiku-4-5-20251001", "modelUsage"),
        ]
    )

    assert engine_model_from_transcript(transcript) == "claude-opus-5-5"
    assert engine_models_in_transcript(transcript) == ["claude-opus-5-5", "claude-haiku-4-5-20251001"]


# --- what the turn records -----------------------------------------------------


def test_a_turn_records_both_the_request_and_the_model_that_answered(tmp_path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    conversation = forge_code_store.new_conversation(root, title="a build")

    saved = forge_code_store.append_agent_turn(
        root,
        conversation["id"],
        model="claude:opus",
        model_used="claude-opus-5-5",
        transcript=json.dumps({"fc": "final", "text": "done"}),
        changed_files=["a.py"],
        returncode=0,
        ok=True,
        noop=False,
        reason="1 file(s) changed",
    )

    turn = saved["turns"][-1]
    assert turn["model"] == "claude:opus", "what was asked for is still recorded"
    assert turn["model_used"] == "claude-opus-5-5", "and now so is what answered"

    summary = next(row for row in forge_code_store.list_conversations(root) if row["id"] == conversation["id"])
    assert summary["last_model"] == "claude:opus"
    assert summary["last_model_used"] == "claude-opus-5-5"


def test_a_run_that_reported_no_model_says_so_by_omission(tmp_path) -> None:
    """An absent key is a different fact from "it ran the alias" and stays so."""
    root = tmp_path / "project"
    root.mkdir()
    conversation = forge_code_store.new_conversation(root, title="a build")

    saved = forge_code_store.append_agent_turn(
        root,
        conversation["id"],
        model="gpt-5.5",
        transcript="",
        changed_files=[],
        returncode=0,
        ok=False,
        noop=True,
        reason="no change made",
    )

    assert "model_used" not in saved["turns"][-1]
    summary = next(row for row in forge_code_store.list_conversations(root) if row["id"] == conversation["id"])
    assert summary["last_model_used"] == ""


class _ExitedRun:
    """A runner that already finished; its transcript is on disk."""

    returncode = 0

    class stdout:  # noqa: N801 - mirrors asyncio's attribute name
        @staticmethod
        async def readline() -> bytes:
            return b""

        @staticmethod
        async def read(_n: int = -1) -> bytes:
            return b""

    async def wait(self) -> int:
        return 0


def test_the_server_recorder_saves_the_model_and_teaches_its_own_menu(tmp_path) -> None:
    """The runner is another process, so the server has to learn the alias itself.

    Its in-process cache would otherwise keep labelling `opus` unchecked until
    a restart, however many runs had reported it.
    """
    import asyncio

    from aiohttp import web

    from tests.test_evolve_agent_routes import _new_repo
    from thomas.forge.anvil import forge_code_git
    from thomas.server.routes import evolve_agent_runtime

    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    receipt = ClaudeStreamTranslator()(INIT_LINE)[0]
    transcript.write_text(
        json.dumps(receipt) + "\n" + json.dumps({"fc": "final", "text": "ready"}) + "\n", encoding="utf-8"
    )
    assert claude_alias_ids.alias_label("opus", listed=())[0] == "Claude Opus"

    asyncio.run(
        evolve_agent_runtime._drain_and_record(
            _ExitedRun(),
            transcript,
            repo,
            conversation["id"],
            "claude:opus",
            forge_code_git.snapshot(repo),
            web.Application(),
            run_id="run-model-receipt",
        )
    )

    turn = forge_code_store.load_conversation(repo, conversation["id"])["turns"][-1]
    assert (turn["model"], turn["model_used"]) == ("claude:opus", "claude-opus-5-5")
    assert claude_alias_ids.alias_label("opus", listed=())[0] == "Claude Opus (claude-opus-5-5)"


# --- what the label is allowed to claim ----------------------------------------


def test_no_alias_is_ever_labelled_newest() -> None:
    """The word that was wrong. It is not in any label, checked or unchecked."""
    from thomas.models.sources.claude_cli import claude_cli_aliases

    for row in claude_cli_aliases():
        assert "newest" not in row.display_name.lower(), row.display_name


def test_an_unchecked_alias_names_no_exact_model() -> None:
    name, description = claude_alias_ids.alias_label("opus", listed=frozenset())

    assert name == "Claude Opus"
    assert "claude-opus" not in description, "nothing has told us which Opus yet"
    assert "records it" in description


def test_the_engine_report_is_what_the_label_repeats() -> None:
    assert claude_alias_ids.remember_engine_model("claude:opus", "claude-opus-5-5") is True

    name, description = claude_alias_ids.alias_label("opus")

    assert name == "Claude Opus (claude-opus-5-5)"
    assert description == "Claude Code's `opus` started claude-opus-5-5 here."
    assert claude_alias_ids.resolve_alias("opus") == ("claude-opus-5-5", "engine")


def test_the_provider_list_answers_a_different_question_and_says_which(tmp_path) -> None:
    """Anthropic's newest Opus is not a claim about what ``opus`` starts.

    The two disagreed on Claude Code 2.1.278 -- ``opus`` started claude-opus-5
    while claude-opus-5-5 was listed -- which is the whole reason the label was
    wrong. So a provider-list answer never reaches the display name.
    """
    listed = frozenset({"claude-opus-5", "claude-opus-5-5", "claude-opus-4-1-20250805", "claude-sonnet-5"})

    assert claude_alias_ids.newest_listed_for("opus", listed) == "claude-opus-5-5"
    assert claude_alias_ids.resolve_alias("opus", listed) == ("claude-opus-5-5", "provider-list")

    name, description = claude_alias_ids.alias_label("opus", listed)
    assert name == "Claude Opus", "the exact id stays out of the name until the engine confirms it"
    assert "unchecked here" in description


def test_the_engine_outranks_the_provider_list() -> None:
    listed = frozenset({"claude-opus-5-5"})
    claude_alias_ids.remember_engine_model("opus", "claude-opus-5")

    assert claude_alias_ids.resolve_alias("opus", listed) == ("claude-opus-5", "engine")


def test_an_alias_echoed_back_at_us_resolves_nothing() -> None:
    """An engine answering "opus" to "opus" has not told us which model ran."""
    assert claude_alias_ids.remember_engine_model("opus", "opus") is False
    assert claude_alias_ids.engine_model_for("opus") == ""


def test_an_exact_id_request_teaches_nothing_about_an_alias() -> None:
    assert claude_alias_ids.remember_engine_model("claude-opus-5-5", "claude-opus-5-5") is False
    assert claude_alias_ids.normalize_alias("claude-opus-5-5") == ""
    assert claude_alias_ids.normalize_alias("claude:OPUS") == "opus"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_code_view_turn_header_names_the_model_that_answered() -> None:
    """The unified Code view's turn header showed ``turn.model`` -- the request."""
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "node",
            str(repo / "tests" / "web_node" / "a_turn_names_the_model_that_answered.mjs"),
            str(repo / "thomas" / "server" / "web" / "js" / "unified_code_events.js"),
        ],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    html = json.loads(result.stdout)
    # Since the 2026-11 Build redesign the head shows only "Thomas" (you asked for nothing beside his
    # name), so what answered moved to the name's hover title -- still the model that RAN, not the request.
    assert '<strong title="Ran on claude-opus-5-5 (asked for claude:opus)">Thomas</strong>' in html["reported"]
    assert "Workspace update" not in html["reported"]
    # A turn with no report -- recorded before this existed, or an engine that
    # never said -- names what it asked for AND says the model went unreported,
    # instead of looking exactly like a turn whose request is the whole story.
    assert (
        '<strong title="Asked for claude:opus; the engine did not report which exact model ran this turn">'
        "Thomas</strong>"
    ) in html["unreported"]


# --- a run that names a second model -------------------------------------------


def test_only_the_model_the_run_started_teaches_the_alias() -> None:
    """``modelUsage`` also names helper models; none of them is what ``opus`` starts."""
    from thomas.forge.anvil.build_model_receipt import started_model

    assert started_model(json.loads(_receipt("claude-opus-5-5", "init"))) == "claude-opus-5-5"
    assert started_model(json.loads(_receipt("claude-haiku-4-5-20251001", "modelUsage"))) == ""
    assert started_model(json.loads(_receipt("claude-opus-5-5", "assistant"))) == ""
    assert started_model({"fc": "meta", "model": "claude-opus-5-5", "source": "init"}) == ""


def test_a_two_model_run_leaves_opus_labelled_with_the_model_it_started(tmp_path) -> None:
    """Drive F: init opus-5-5, modelUsage {opus-5-5, haiku}. The menu said opus started Haiku."""
    import asyncio

    from aiohttp import web

    from tests.test_evolve_agent_routes import _new_repo
    from thomas.forge.anvil import forge_code_git
    from thomas.server.routes import evolve_agent_runtime

    translate = ClaudeStreamTranslator()
    two_models = json.dumps(
        {
            "type": "result",
            "result": "ok",
            "modelUsage": {"claude-opus-5-5": {"inputTokens": 4}, "claude-haiku-4-5-20251001": {"inputTokens": 2}},
        }
    )
    lines = [*translate(INIT_LINE), *translate(two_models)]
    assert [e["model"] for e in lines if is_model_receipt(e)] == ["claude-opus-5-5", "claude-haiku-4-5-20251001"]

    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text("\n".join(json.dumps(e) for e in lines) + "\n", encoding="utf-8")

    asyncio.run(
        evolve_agent_runtime._drain_and_record(
            _ExitedRun(),
            transcript,
            repo,
            conversation["id"],
            "claude:opus",
            forge_code_git.snapshot(repo),
            web.Application(),
            run_id="run-two-models",
        )
    )

    turn = forge_code_store.load_conversation(repo, conversation["id"])["turns"][-1]
    assert turn["model_used"] == "claude-opus-5-5"
    assert claude_alias_ids.engine_model_for("opus") == "claude-opus-5-5"
    assert claude_alias_ids.alias_label("opus", listed=())[1] == "Claude Code's `opus` started claude-opus-5-5 here."


def test_a_wrong_value_another_process_left_on_disk_is_corrected(tmp_path) -> None:
    """Drive B2: the server's copy already matched, so it never rewrote the file.

    The false label then came back on the next restart. Saving compares against
    the file, which is shared with the Build runner, not the cache.
    """
    assert claude_alias_ids.remember_engine_model("opus", "claude-opus-5-5") is True
    store = tmp_path / "home" / "claude_alias_ids.json"
    # What an older runner that taught from every receipt would have written.
    store.write_text(json.dumps({"opus": "claude-haiku-4-5-20251001"}), encoding="utf-8")

    assert claude_alias_ids.remember_engine_model("opus", "claude-opus-5-5") is True
    assert json.loads(store.read_text(encoding="utf-8")) == {"opus": "claude-opus-5-5"}
    claude_alias_ids.forget_observations()  # a restart
    assert claude_alias_ids.engine_model_for("opus") == "claude-opus-5-5"


# --- a GPT Build turn ------------------------------------------------------------


def test_the_codex_stream_carries_the_model_the_provider_named() -> None:
    """``response.model`` in response.created/completed used to be dropped."""
    from tests.test_llm_openai_tool_compat import _codex_client, _collect_events, _FakeClient

    lines = [
        "event: response.created",
        'data: {"type":"response.created","response":{"model":"gpt-5.5-2026-08-01"}}',
        "",
        "event: response.output_text.delta",
        'data: {"type":"response.output_text.delta","delta":"hi"}',
        "",
        "event: response.completed",
        'data: {"type":"response.completed","response":{"model":"gpt-5.5-2026-08-01",'
        '"usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2}}}',
        "",
    ]

    events = _collect_events(_codex_client(_FakeClient(lines), retries=1))

    done = [e for e in events if e.type == "done"]
    assert [e.data.get("model") for e in done] == ["gpt-5.5-2026-08-01"]


def test_the_anthropic_api_stream_carries_the_model_it_named() -> None:
    """A Claude profile with an API key runs the same loop; ``message_start`` names the model."""
    import asyncio

    from tests.test_llm_anthropic_usage import TestAnthropicUsageAccounting

    llm = TestAnthropicUsageAccounting()._make_client(
        [
            'data: {"type":"message_start","message":{"model":"claude-opus-5-5","usage":{"input_tokens":1}}}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}',
            'data: {"type":"message_stop"}',
        ]
    )

    async def run_once():
        return [ev async for ev in llm.stream_chat([{"role": "user", "content": "hello"}], tools=None)]

    done = [e for e in asyncio.run(run_once()) if e.type == "done"]
    assert [e.data.get("model") for e in done] == ["claude-opus-5-5"]


def test_the_agent_loop_passes_the_provider_model_on() -> None:
    import asyncio

    from tests.test_agent_loop_conversation import make_agent
    from thomas.core.events import EventType
    from thomas.core.llm import StreamEvent

    agent, llm, _ = make_agent()

    async def stream_chat(messages, tools, **_kwargs):  # noqa: ANN001
        yield StreamEvent(type="token", data={"text": "hi"})
        yield StreamEvent(type="done", data={"model": "gpt-5.5-2026-08-01"})

    llm.stream_chat = stream_chat

    async def run_once():
        return [event async for event in agent.run("hello", tools_policy="never")]

    reported = [e.data["model"] for e in asyncio.run(run_once()) if e.type == EventType.MODEL_REPORTED]
    assert reported and set(reported) == {"gpt-5.5-2026-08-01"}


def test_a_gpt_build_turn_records_the_model_the_provider_reported() -> None:
    """Drive D: the GPT translator wrote no receipt, so the turn had no ``model_used``."""
    from thomas.core.events import EventType
    from thomas.forge.anvil.dispatch_agent_loop_translator import _AgentLoopForgeTranslator

    emitted: list[dict] = []
    translator = _AgentLoopForgeTranslator(emitted.append)
    for _call in range(3):  # one report per model call; the run makes several
        translator.feed(EventType.MODEL_REPORTED.value, {"model": "gpt-5.5-2026-08-01"})
    translator.feed(EventType.AGENT_DONE.value, {"text": "done"})

    receipts = [e for e in emitted if is_model_receipt(e)]
    assert [(e["model"], e["source"]) for e in receipts] == [("gpt-5.5-2026-08-01", "provider")]
    transcript = "\n".join(json.dumps(e) for e in emitted)
    assert engine_model_from_transcript(transcript) == "gpt-5.5-2026-08-01"


def test_the_rail_summary_never_borrows_an_older_turns_model(tmp_path) -> None:
    """The rail pairs `last_model` with `last_model_used`; they must be one turn's."""
    root = tmp_path / "project"
    root.mkdir()
    conversation = forge_code_store.new_conversation(root, title="a build")
    common = {"transcript": "", "changed_files": [], "returncode": 0, "ok": True, "noop": False, "reason": ""}
    forge_code_store.append_agent_turn(
        root, conversation["id"], model="claude:opus", model_used="claude-opus-5-5", **common
    )
    forge_code_store.append_agent_turn(root, conversation["id"], model="claude:sonnet", **common)

    summary = next(row for row in forge_code_store.list_conversations(root) if row["id"] == conversation["id"])
    assert (summary["last_model"], summary["last_model_used"]) == ("claude:sonnet", "")


# --- the picker and the provider list --------------------------------------------


def test_a_dated_base_version_does_not_outrank_a_newer_point_release() -> None:
    """Drive E: raw digit tuples put (4, 20250514) above (4, 5, 20250929)."""
    listed = frozenset({"claude-sonnet-4-20250514", "claude-sonnet-4-5-20250929", "claude-3-5-sonnet-20241022"})

    assert claude_alias_ids.newest_listed_for("sonnet", listed) == "claude-sonnet-4-5-20250929"
    assert claude_alias_ids.newest_listed_for("opus", {"claude-opus-4-20250514", "claude-opus-4-1-20250805"}) == (
        "claude-opus-4-1-20250805"
    )


def test_the_picker_relabels_a_cached_alias_row_as_soon_as_a_run_reports() -> None:
    """The cached catalog froze the label until the next refresh, up to half a day."""
    from thomas.models.catalog import catalog_view

    cached = {"models": [{"id": "opus", "family": "anthropic", "display_name": "Claude Opus", "description": "x"}]}
    assert catalog_view(cached)["models"][0]["display_name"] == "Claude Opus"

    claude_alias_ids.remember_engine_model("claude:opus", "claude-opus-5-5")

    row = catalog_view(cached)["models"][0]
    assert row["display_name"] == "Claude Opus (claude-opus-5-5)"
    assert row["description"] == "Claude Code's `opus` started claude-opus-5-5 here."
    assert cached["models"][0]["display_name"] == "Claude Opus", "the cache itself is not rewritten"
