from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.web_fixtures.chat_sources import read_chat_sources
from thomas.chat.session_store import SessionMeta
from thomas.server.app_routes_init import _v2_sessions_as_chats
from thomas.server.routes.chat_surface_namespace import (
    parse_chat_surface_namespace,
    session_namespace_matches,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = REPO_ROOT / "thomas" / "server" / "web" / "chat.html"
# chat.html's one inline <style> was lifted here when the page passed its own
# 3000-line ceiling. Rules asserted below live in the stylesheet, not the page.
CHAT_SHELL_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "chat_shell.css"
WORK_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_work_mode.js"
CODE_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_mode.js"
CODE_LIFECYCLE_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_lifecycle.js"
# Siblings chat.html loads ahead of unified_code_mode.js. The node harnesses
# below have to load them in the same order the browser does, or the adapter
# hands its collaborators to a module that is not there yet.
CODE_ARTIFACTS_JS = REPO_ROOT / "thomas/server/web/js/unified_code_artifacts.js"
CODE_RESULTS_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_results.js"
CODE_PROJECTS_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_projects.js"
# The event-render cluster left unified_code_mode.js to get it under its size
# ceiling. It is a sibling like the rest: loaded first, configured at load time.
CODE_EVENTS_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_events.js"
# The pieces a turn is drawn from since the 2026-10 Build redesign (work rows,
# cards, the head); the event cluster calls into them, so they load before it.
CODE_CARDS_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_cards.js"
CODE_VIEW_STATE_JS = REPO_ROOT / "thomas/server/web/js/unified_code_view_state.js"
CODE_LIVE_VIEW_JS = REPO_ROOT / "thomas/server/web/js/unified_code_live_view.js"
CODE_SURFACE_JS = REPO_ROOT / "thomas/server/web/js/unified_code_surface.js"
CODE_RUN_STREAM_JS = REPO_ROOT / "thomas/server/web/js/unified_code_run_stream.js"
# The 2026-10 Build redesign's modules: the agents (roster, drawer, side chat),
# the live diff, the composer's controls, and the run controls that wire them.
CODE_REDESIGN_JS = tuple(
    REPO_ROOT / "thomas/server/web/js" / f"unified_code_{name}.js"
    for name in ("roster", "drawer", "agent_chat", "live_diff", "composer")
)
CODE_QUESTIONS_JS = REPO_ROOT / "thomas/server/web/js/unified_code_questions.js"
CODE_CONTROLS_JS = REPO_ROOT / "thomas/server/web/js/unified_code_controls.js"
CODE_CONTINUATION_JS = REPO_ROOT / "thomas/server/web/js/unified_code_continuation.js"
CODE_HISTORY_ROWS_JS = REPO_ROOT / "thomas/server/web/js/unified_code_history_rows.js"
CODE_LOADING_JS = REPO_ROOT / "thomas/server/web/js/unified_code_loading.js"
CODE_SIBLING_JS = (
    CODE_VIEW_STATE_JS,
    CODE_ARTIFACTS_JS,
    CODE_RESULTS_JS,
    CODE_PROJECTS_JS,
    *CODE_REDESIGN_JS,
    CODE_CARDS_JS,
    CODE_EVENTS_JS,
    CODE_LIVE_VIEW_JS,
    CODE_SURFACE_JS,
    CODE_RUN_STREAM_JS,
    CODE_QUESTIONS_JS,
    CODE_CONTROLS_JS,
    CODE_CONTINUATION_JS,
    CODE_HISTORY_ROWS_JS,
    CODE_LOADING_JS,
)
# Assertions about how a run is rendered do not care which side of that split
# the code sits on, so they read both. A negative assertion gets stronger this
# way: the markup must be absent from the pair, not merely from one file.
CODE_RENDER_SOURCES = (CODE_JS, CODE_CARDS_JS, CODE_EVENTS_JS, CODE_LIVE_VIEW_JS, CODE_SURFACE_JS, CODE_RUN_STREAM_JS)
CODE_LIFECYCLE_HARNESS = REPO_ROOT / "tests" / "web_node" / "unified_code_mode_lifecycle.mjs"
WORK_SUPPORT_HARNESS = REPO_ROOT / "tests" / "web_node" / "unified_work_support_lifecycle.mjs"


def test_primary_chat_has_accessible_three_mode_selector_above_search() -> None:
    text = read_chat_sources(CHAT_HTML)

    selector = text.index('id="tc-mode-switch"')
    search = text.index('id="tc-search"')
    assert selector < search
    assert text.count('data-thomas-mode="chat"') == 1
    assert text.count('data-thomas-mode="code"') == 1
    assert text.count('data-thomas-mode="work"') == 1
    assert 'role="tablist"' in text
    assert 'aria-selected="true"' in text


def test_primary_chat_loads_real_mode_adapters_not_classic_iframes() -> None:
    text = read_chat_sources(CHAT_HTML)

    assert "/static/js/unified_mode_shell.js" in text
    assert "/static/js/unified_code_lifecycle.js" in text
    assert "/static/js/unified_code_results.js" in text
    assert "/static/js/unified_code_projects.js" in text
    assert "/static/js/unified_code_mode.js" in text
    assert "/static/js/unified_work_mode.js" in text
    # The shared shell stylesheet is REQUIRED: it owns the
    # #tc-shell[data-surface-mode] visibility flips that reveal the Code/Work
    # workspace. The per-surface modules (split under the CSS growth caps)
    # complement it, never replace it — dropping it left the mode surface
    # permanently hidden (P1, 2026-07-19).
    assert "/static/css/unified_modes.css" in text
    assert "/static/css/unified_code_mode.css" in text
    assert "/static/css/unified_code_activity.css" in text
    assert "/static/css/unified_code_results.css" in text
    assert "/static/css/unified_work_mode.css" in text
    assert "/static/css/unified_work_details.css" in text
    assert 'id="tc-mode-surface"' in text
    assert "fetch('/api/chats?mode=chat')" in text
    assert "surface_mode: 'chat'" in text
    # unified_code_mode.js hands its state, escaper and render to the siblings at
    # load time, so every one of them must already be on the page. Ordering is
    # the whole contract between these four files.
    for sibling in (
        "unified_code_lifecycle.js",
        "unified_code_artifacts.js",
        "unified_code_results.js",
        "unified_code_projects.js",
        "unified_code_events.js",
        "unified_code_live_view.js",
        "unified_code_surface.js",
        "unified_code_run_stream.js",
        "unified_code_questions.js",
        "unified_code_controls.js",
    ):
        assert text.index(f"/static/js/{sibling}") < text.index("/static/js/unified_code_mode.js")


def test_chat_busy_transitions_refresh_shared_mode_chrome() -> None:
    text = read_chat_sources(CHAT_HTML)

    assert "deps.state.streaming = true; deps.setExternalBusy();" in text
    assert (
        "deps.state.streaming = false; deps.abortController = null;\ndeps.updateStreamingBubble(idx); deps.renderActivity(idx); deps.setExternalBusy();"
        in "\n".join(line.strip() for line in text.splitlines())
    )


def test_verified_artifacts_offer_explicit_attachment_downloads() -> None:
    text = read_chat_sources(CHAT_HTML)

    assert "function artifactDownloadUrl(url)" in text
    assert "data-artifact-download" in text
    assert "download=1" in text


def test_primary_modes_do_not_duplicate_legacy_forge_or_workforce_navigation() -> None:
    text = read_chat_sources(CHAT_HTML)
    workspace_list = text[text.index("const workspaces = [") : text.index("];", text.index("const workspaces = ["))]

    assert "label: 'Forge'" not in workspace_list
    assert "label: 'Workforce'" not in workspace_list


def test_primary_chat_cancel_button_requests_durable_session_scoped_cancellation() -> None:
    text = read_chat_sources(CHAT_HTML)

    assert "async function requestTaskCancel(sessionId, executionId)" in text
    assert "'/delegations/' + encodeURIComponent(executionId) + '/cancel'" in text
    # Cancellation moved into the helper that the live shell calls. Inspect both
    # sides of that binding so an unreferenced passing helper cannot satisfy it.
    flow = (REPO_ROOT / "thomas/server/web/js/chat_turn_flow.js").read_text(encoding="utf-8")
    assert "return window.ThomasChatTurnFlow.cancelTask({" in text
    assert "getController: () => deps.abortController" in text
    assert "cancelTask: cancelTask" in flow
    assert "Promise.allSettled(executionIds.map(id => requestTaskCancel" in flow
    assert "payload.ok !== true" in text
    assert "unreadable cancellation response" in text
    assert "catch (error) { payload = {}; }" not in text
    assert "there is no direct cancel endpoint yet" not in text


def test_primary_chat_renders_honest_tool_and_observed_model_receipts() -> None:
    text = read_chat_sources(CHAT_HTML)

    assert "finishToolStep(idx, evt.ok !== false)" in text
    assert "function applyModelRuntimeReceipt(idx, runtime)" in text
    assert "type === 'model_runtime'" in text
    assert "fallback used" in text
    assert "Verified: this model produced this reply" in text
    assert "const observedId =" in text


def test_session_meta_round_trips_surface_namespace() -> None:
    original = SessionMeta(
        session_id="work-session",
        surface_mode="work",
        context_id="job-42",
        profile="openai_codex",
        model_id="gpt-5.6-terra",
        reasoning_effort="high",
    )

    restored = SessionMeta.from_dict(original.to_dict())

    assert restored.surface_mode == "work"
    assert restored.context_id == "job-42"
    assert restored.model_id == "gpt-5.6-terra"


def test_v2_sidebar_rows_expose_mode_and_context(tmp_path: Path) -> None:
    payload = {
        "session_id": "work-session",
        "saved_at": 1_720_000_000.0,
        "conversation": {
            "messages": [
                {"role": "user", "content": "Run the morning inbox job"},
                {"role": "assistant", "content": "Starting the verified run."},
            ]
        },
        "meta": SessionMeta(
            session_id="work-session",
            surface_mode="work",
            context_id="job-42",
        ).to_dict(),
    }
    (tmp_path / "chat_work.json").write_text(json.dumps(payload), encoding="utf-8")

    rows = _v2_sessions_as_chats(tmp_path)

    assert rows[0]["surfaceMode"] == "work"
    assert rows[0]["contextId"] == "job-42"
    assert rows[0]["title"] == "Run the morning inbox job"


def test_work_adapter_uses_real_scoped_apis_and_mission_deployment() -> None:
    text = WORK_JS.read_text(encoding="utf-8")

    assert "'/api/work/apps'" in text
    assert "'/api/work/accounts'" in text
    assert "surface_mode: 'work'" in text
    assert "/automations/" in text and "/deploy" in text
    assert "/bindings" in text
    assert "/skills" in text
    assert "Private Thomas Work onboarding context" in text
    assert "window.prompt" not in text


def test_work_onboarding_uses_structured_state_and_explicit_selection() -> None:
    completed = subprocess.run(
        [
            "node",
            str(WORK_SUPPORT_HARNESS),
            str(REPO_ROOT / "thomas/server/web/js/unified_work_support.js"),
            str(WORK_JS),
            # A refused steer is worded once for every surface that has a steer
            # box; the adapter reads that table, so the harness loads it too.
            str(REPO_ROOT / "thomas/server/web/js/steering_language.js"),
            # The Work card's live tasks and steer boxes live in their own
            # module, which the adapter creates when it loads.
            str(REPO_ROOT / "thomas/server/web/js/unified_work_mode_steer.js"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"structuredWorkflowState":true' in completed.stdout
    assert '"proseCannotSelectWorkflow":true' in completed.stdout
    assert '"firstTurnHiddenCompletion":true' in completed.stdout
    assert '"reconciliationExecuted":true' in completed.stdout
    assert '"activeDraftRequeued":true' in completed.stdout
    assert '"workSteerSameTask":true' in completed.stdout
    assert '"workSteerRefusalExplained":true' in completed.stdout
    # Several tasks can run at once, and each steer box keeps its own half-typed
    # note through the repaint that every progress line causes.
    assert '"workSteerDraftsPerTask":true' in completed.stdout
    assert '"workProgressStates":true' in completed.stdout


def test_work_styles_are_decomposed_and_loaded_in_order() -> None:
    text = read_chat_sources(CHAT_HTML)

    mode = text.index("/static/css/unified_work_mode.css")
    details = text.index("/static/css/unified_work_details.css")
    assert mode < details
    line_caps = {
        "unified_work_mode.css": 650,
        "unified_work_details.css": 600,
    }
    for relative, line_cap in line_caps.items():
        lines = (REPO_ROOT / "thomas/server/web/css" / relative).read_text(encoding="utf-8").splitlines()
        assert len(lines) <= line_cap


def test_work_adapter_hides_without_cancelling_the_active_stream() -> None:
    text = WORK_JS.read_text(encoding="utf-8")
    leave_body = text[text.index("async function leave()") : text.index("modes().registerAdapter('work'")]

    assert "async function leave()" in text
    assert "adapterActive = false" in text
    assert "selectionGeneration += 1" in text
    assert "generation !== selectionGeneration" in text
    assert "if (!adapterActive) return" in text
    assert "clearTimeout(reconcileTimer)" in text
    assert "activeStreamController.abort()" not in leave_body
    assert "state.running = false" not in leave_body
    assert "selectionGeneration += 1" not in leave_body
    assert "function stop()" in text
    assert "isBusy: () => state.running" in text
    assert "void safely(() => openJob" in text


def test_work_adapter_contains_async_ui_failures_and_clears_stale_error() -> None:
    text = WORK_JS.read_text(encoding="utf-8")

    assert "async function safely(action)" in text
    assert "state.error = error && error.message" in text
    assert "state.error = '';" in text
    assert "void safely(() => openApp" in text
    assert "void safely(() => deployAutomation" in text
    assert "void safely(() => approvePromotion" in text


def test_code_adapter_uses_real_forge_runtime_and_change_controls() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in (CODE_JS, CODE_SURFACE_JS, CODE_RUN_STREAM_JS)
    ).replace("deps.", "") + CODE_LIFECYCLE_JS.read_text(encoding="utf-8")
    text += "".join(path.read_text(encoding="utf-8") for path in CODE_SIBLING_JS)

    assert "'/api/evolve/agent/send'" in text
    assert "/api/evolve/agent/stream" in text
    assert "loadChanges" in text
    assert "data-code-keep" in text
    assert "data-code-revert" in text
    assert "requestSettings" in text
    assert "Array.isArray(data.entries)" in text
    assert "row.kind === 'directory'" in text
    assert "tc-code-artifact" in text
    assert 'sandbox="allow-scripts allow-forms allow-same-origin"' in text


def test_code_adapter_contains_async_failures_at_ui_boundaries() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in (CODE_JS, CODE_SURFACE_JS, CODE_RUN_STREAM_JS, CODE_CONTROLS_JS)
    ).replace("deps.", "")

    assert "async function safely(action, fallback)" in text
    # Both stop entry points -- the composer's primary button (Stop for a run
    # that cannot pause; it replaced the drawer's Stop in the 2026-10 redesign)
    # and the mode adapter -- run the SAME routine. There used to be a second
    # `stop()` behind the adapter with different wording and no refresh;
    # pinning the shared call is what keeps a third stop from drifting in again.
    assert text.count("void safely(() => stopRun()") == 2
    assert "void safely(() => loadTree" in text
    assert "void safely(() => loadFile" in text
    assert "void safely(approvePending" in text
    # The queue's Steer falls back to the stop-and-continue steer, guarded too.
    assert "await safely(() => steer(" in text
    # newConversation takes a project root and label (the library picker names
    # what it chose), so match the containment rather than a zero-argument form.
    assert "safely(() => newConversation(projectRoot, projectLabel, options)" in text
    # Only what you typed in the composer can answer an open question.
    assert "send: (message, context) => safely(() => send(message, context, { typed: true })" in text
    assert "Promise.allSettled" in text


def test_code_adapter_preserves_terminal_stream_states() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in (CODE_JS, CODE_SURFACE_JS, CODE_RUN_STREAM_JS)
    ).replace("deps.", "")

    assert "state.source !== source" in text
    assert "state.runStatus = terminalRunStatus(payload)" in text
    assert "state.runStatus = 'disconnected'" in text
    assert "state.runStatus = 'stopped'" in text
    # The unified stop routine does not trust the stop response's own claim of
    # termination: it polls status until the run is genuinely gone before
    # declaring the stop, which is what `payload.termination_confirmed` used to
    # gate in the retired second stop function.
    assert "await waitForRestartReady()" in text
    assert "state.runStatus = 'stopping'" in text
    assert "const stopWasPending = state.runStatus === 'stopping'" in text
    # The live stop confirmation speaks in plain words. It used to interpolate
    # the process exit code -- "Stop confirmed (process exit 1)." -- which
    # reads as an error for a deliberate, clean user stop.
    assert "Stopped — Thomas is wrapping up the record." in text
    assert "process exit ${payload.returncode}" not in text
    assert "loadConversation(id, { internal: true, epoch, deferRender: true })" in text
    assert "approvalBusy" in text
    assert "steeringBusy" in text
    leave_body = text[text.index("async function leave()") : text.index("modes().registerAdapter('code'")]
    assert "closeSource()" not in leave_body
    assert "finishBusy()" not in leave_body
    assert "adapterActive = false" in leave_body


def test_code_adapter_collapses_terminal_and_tool_evidence_behind_details() -> None:
    text = "".join(p.read_text(encoding="utf-8") for p in CODE_RENDER_SOURCES)
    css = (REPO_ROOT / "thomas/server/web/css/unified_code_activity.css").read_text(encoding="utf-8")

    assert "function isTerminalTool(name)" in text
    assert "function annotateTerminalEvent(event, tracker)" in text
    # 2026-10 Build redesign: the grouped "Worked through …" block is gone and
    # every step is one work row -- a <details> whose summary is a single dim
    # line and whose body holds the full output. Repeats still merge into ×N.
    assert "function workRowHtml(ev, opts)" in text
    assert '<details class="tc-code-work tc-code-receipt tc-code-technical' in text
    assert "<pre>${esc(full)}</pre>" in text, "the full output no longer sits behind the row"
    assert "tc-code-receipt-count" not in text, "identical rows are not merged into a count"
    assert '<details class="tc-code-technical' not in text
    assert "Ran terminal command" in text
    assert "Read terminal result" in text
    # The run's outcome still frames recovered tool errors ("failed attempts,
    # recovered" on an ok run, "issues" otherwise).
    assert "Worked through" in text
    assert "technicalSummary(technicalEvents, turn.ok === true)" in text
    assert ".tc-code-technical-log" in css
    assert ".tc-code-technical:not(.tc-code-receipt) code" in css
    # The old icon/body grid must not squeeze a disclosure summary into its
    # 16px icon column. Receipts have their own full-width flex summary.
    assert ".tc-code-technical { display: grid" not in css
    assert ".tc-code-technical:not(.tc-code-receipt) { display: grid" in css
    assert "function projectActionsHtml()" not in text
    assert "data-code-drawer-close" in text
    assert "Build a game" not in text
    assert "show work" not in text, "a long run's steps fold behind nothing: every row shows"


def test_code_history_is_global_title_only_and_omits_empty_drafts() -> None:
    harness = r"""
const fs = require('fs');
let adapter = null;
global.window = {
  ThomasUnifiedModes: {
    host: () => ({ renderHistory: () => {} }),
    registerAdapter: (_mode, value) => { adapter = value; },
  },
};
global.document = {
  getElementById: () => null,
  createElement: () => ({
    type: '',
    className: '',
    innerHTML: '',
    // Real elements always carry `dataset`; the renderers tag rows with
    // data-history-* so the shared sidebar decorator can sort and act on them.
    dataset: {},
    classList: { add: () => {}, toggle: () => {}, contains: () => false },
    addEventListener: () => {},
    querySelector: () => null,
  }),
};
global.localStorage = { getItem: () => 'C:\\Repos\\Chosen\\' };
global.fetch = async () => ({
  ok: true,
  json: async () => ({ conversations: [
    { id: 'chosen', title: 'Chosen build', project_root: 'c:/repos/chosen', turn_count: 2 },
    { id: 'other', title: 'Other build', project_root: 'C:/Repos/Other', turn_count: 1 },
    { id: 'empty', title: 'Untitled build', project_root: 'C:/Repos/Empty', turn_count: 0 },
  ] }),
});
for (const modulePath of process.argv.slice(1)) eval(fs.readFileSync(modulePath, 'utf8'));
(async () => {
  await adapter.refresh();
  const root = { innerHTML: '', children: [], appendChild(node) { this.children.push(node); } };
  adapter.renderHistory(root, '');
  const rendered = root.children.map(row => row.innerHTML).join('|');
  if (root.children.length !== 2 || !rendered.includes('Chosen build') || !rendered.includes('Other build')) {
    throw new Error(`title history was incomplete: ${rendered}`);
  }
  if (/project_root|repos\/|C:\\Repos/i.test(rendered) || rendered.includes('Untitled build')) {
    throw new Error(`history leaked paths or empty drafts: ${rendered}`);
  }
})().catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
"""

    result = subprocess.run(
        # Siblings first, exactly as chat.html orders the script tags. These are
        # this repository's own checked-in files, not input.
        ["node", "-e", harness, *[str(path) for path in CODE_SIBLING_JS], str(CODE_JS)],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr


def test_code_history_replays_persisted_run_activity() -> None:
    text = "".join(p.read_text(encoding="utf-8") for p in CODE_RENDER_SOURCES)

    assert "function transcriptEvents(turn)" in text
    assert "JSON.parse(line)" in text
    assert "parsed && parsed.fc" in text
    assert "const events = transcriptEvents(turn)" in text
    # OWNER REDLINE 2026-08-10: a saved turn no longer renders its evidence as
    # one collapsed block after the narrative. Receipts are interleaved with
    # the sentences they back up, and the run-outcome framing is kept by the
    # recovered-attempt note. The property this pins -- a persisted turn
    # replays its recorded activity, with the ok/failed distinction intact --
    # is unchanged, so it is asserted against the current renderers.
    assert "interleavedActivityHtml(activityEvents, true)" in text
    assert "technicalSummary(technicalEvents, turn.ok === true)" in text
    # The replayed steps are work rows (2026-10 redesign), marked as saved.
    assert "cards().workRowsHtml(" in text
    assert 'data-saved="true"' in text


def test_code_surface_uses_chat_conversation_with_collapsible_activity_drawer() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in (CODE_JS, CODE_SURFACE_JS, CODE_RUN_STREAM_JS)
    ).replace("deps.", "")
    css = (REPO_ROOT / "thomas/server/web/css/unified_code_mode.css").read_text(encoding="utf-8")
    html = (REPO_ROOT / "thomas/server/web/chat.html").read_text(encoding="utf-8")

    assert "tc-mode-hero" not in text
    assert "Build with Thomas" not in text
    assert 'class="tc-code-context"' in text
    assert "data-code-results-jump" in text
    assert "state.drawerOpen = !state.drawerOpen" in text
    assert "data-code-drawer-close" in text
    assert 'class="tc-code-project"' not in text
    assert 'aria-label="Build conversation"' in text
    assert 'id="tc-code-live-technical"' in text
    assert 'aria-label="Build activity"' in text
    assert "turns.flatMap(turn => turn.artifacts || [])" in text
    assert ".tc-code-turn.is-user" in css
    assert ".tc-code-message-head" in css
    assert "aria-hidden=\"${state.drawerOpen ? 'false' : 'true'}\"" in text
    assert "${state.drawerOpen ? '' : ' inert'}" in text
    assert 'role="separator"' in text
    assert 'aria-valuenow="${state.drawerWidth}"' in text
    assert ".tc-code-actions" in css and "transform: translateX(calc(100% + 28px))" in css
    assert ".tc-code-panel.is-drawer-open .tc-code-actions" in css
    assert "tc-code-project-btn" in html
    assert "Stop current task" not in text
    assert "projectActionsHtml" not in text
    mobile_css = css[css.index("@media (max-width: 720px)") : css.index("@media (prefers-reduced-motion: reduce)")]
    assert ".tc-code-actions { width: min(420px, 94vw); }" in mobile_css
    # The file tree's own icons must still have a local fallback, so Code reads
    # correctly with no icon font. The fallbacks moved to chat_shell.css with the
    # rest of the shell's inline CSS; the page still has to load it.
    assert "/static/css/chat_shell.css" in html
    shell_css = CHAT_SHELL_CSS.read_text(encoding="utf-8")
    assert ".ph-caret-right::before" in shell_css
    assert ".ph-file-code::before" in shell_css


def test_code_stream_preserves_steering_and_updates_activity_incrementally() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in (CODE_JS, CODE_SURFACE_JS, CODE_RUN_STREAM_JS)
    ).replace("deps.", "") + CODE_LIVE_VIEW_JS.read_text(encoding="utf-8")
    stream_handler = text[text.index("source.onmessage = event =>") : text.index("source.onerror = () =>")]

    view_state = CODE_VIEW_STATE_JS.read_text(encoding="utf-8")
    assert "window.ThomasCodeViewState.capture(root" in text
    assert "window.ThomasCodeViewState.restore(root" in text
    # A field being typed in keeps its caret across a redraw (the in-transcript
    # steer box it was written for is gone; the side chat's box uses it now).
    assert "fieldStart" in view_state and "setSelectionRange" in view_state
    assert "window.ThomasCodeViewState.replaceActivity(surface(), list" in text
    assert "function appendLiveEvent(event, replaceLast)" in text
    assert "appendLiveEvent(payload, replaced)" in stream_handler
    assert "render();" not in stream_handler


def test_code_revert_approval_is_presented_and_retried_with_receipt() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in (CODE_JS, CODE_SURFACE_JS, CODE_RUN_STREAM_JS)
    ).replace("deps.", "")

    assert "data.code === 'approval_required'" in text
    assert "replacePendingApproval(data, { kind: 'change', action, file, request_id: body.request_id })" in text
    assert "delete retry.approval_id" in text
    assert "if (approvalId) body.approval_id = approvalId" in CODE_LIFECYCLE_JS.read_text(encoding="utf-8")
    assert "if (pending.kind === 'change')" in text
    assert (
        "await changeAction(pending.action, pending.file, pending.approval_id, { deferRender: true, requestId: pending.request_id })"
        in text
    )
    assert "state.pendingRequest = pending" in text
    assert "finishBusy();" in text


def test_code_adapter_absorbs_rejected_fetch_promises() -> None:
    harness = r"""
const fs = require('fs');
let adapter = null;
let unhandled = null;
global.window = {
  ThomasUnifiedModes: {
    host: () => ({ setBusy: () => {}, renderHistory: () => {} }),
    registerAdapter: (_mode, value) => { adapter = value; },
  },
};
global.document = { getElementById: () => null };
global.localStorage = { getItem: () => '' };
global.fetch = async () => { throw new Error('offline test'); };
process.on('unhandledRejection', error => { unhandled = error; });
for (const modulePath of process.argv.slice(1)) eval(fs.readFileSync(modulePath, 'utf8'));
(async () => {
  await adapter.newConversation();
  await adapter.send('test rejected send', {});
  await new Promise(resolve => setTimeout(resolve, 25));
  if (unhandled) throw unhandled;
})().catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
"""

    result = subprocess.run(
        # Siblings first, exactly as chat.html orders the script tags. These are
        # this repository's own checked-in files, not input.
        ["node", "-e", harness, *[str(path) for path in CODE_SIBLING_JS], str(CODE_JS)],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr


def test_code_adapter_lifecycle_behavior_in_node() -> None:
    result = subprocess.run(
        [
            "node",
            str(CODE_LIFECYCLE_HARNESS),
            str(CODE_JS),
            str(CODE_LIFECYCLE_JS),
            *[str(path) for path in CODE_SIBLING_JS],
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "approval": True,
        "switch": True,
        "steering": True,
        "evidence": True,
        "stream": True,
        "dedup": True,
        "persistence": True,
        "replay": True,
        "finishing": True,
        "cursor": True,
        "drawer": True,
        "pointercancel": True,
        "picker": True,
        "failureReason": True,
        # A run emitting two `final` events rendered the earlier one as narrative
        # beside the `say` that had streamed the same text -- the same paragraph
        # twice, once headed UPDATE and once THOMAS. Measured on a real failed run
        # at 476 identical characters each.
        "narrativeNotRepeated": True,
        # "What should we make?" and its four starter cards stayed on screen for
        # the whole of a new conversation's first run -- 76 seconds, every sample --
        # above the live turn, with the question just asked nowhere to be seen.
        "emptyStateStandsDown": True,
        # An empty file list has three causes and named only one: for 45 seconds
        # the drawer header named a project while the list beneath it told you to
        # choose one.
        "fileListNamesItsReason": True,
        # After Stop the header read "Thomas - Code - working" directly above its
        # own note saying "Stopped - you interrupted this run".
        "stoppedRunIsNotWorking": True,
        # Reverting a NEW file deletes it, but only the CHANGES list was re-read,
        # so the drawer kept offering a file the server answered 404 for.
        "revertRefreshesFileList": True,
        # A run cut off by its pass budget was summarised as "the final
        # verification still failed after its repair attempts", which sent the
        # owner to inspect a check. It never finished those attempts. The
        # sentence that said what to do -- the task is incomplete, continue it in
        # the same conversation -- was already recorded, and reached nobody: it
        # sat in a risk headed "error surfaced during the run", behind a
        # collapsed Show details, one of two rows sharing that heading.
        "truncatedRunSaysSo": True,
        # The page you SEND from never rendered your own message: turns come
        # from state.conversation, refreshed only from the server, so between
        # pressing Enter and the run finishing your words were nowhere on
        # screen. Measured live at 1920: zero user turns while the live turn
        # streamed. Guarded both ways -- it must appear at once, and must not
        # double when the server copy lands.
        "yourMessageIsOnScreen": True,
        # Every tool_result row read "Checked tool result" -- 27 on one turn,
        # above a folder listing, three "Wrote N chars" lines and a source
        # excerpt, so a file WRITE was labelled a check. The tool name was on
        # the event all along (25 of 27 carried it). And a `meta` event whose
        # text is "Kept index.html." announced itself as "Verified the result".
        "toolRowsNameTheirTool": True,
        # Four consecutive runs of one goal each recorded three events then
        # exited 1 with no error event, and every one told the owner only "The
        # Code task stopped before it finished." -- while `reason` held
        # "exited 1" throughout.
        "silentFailureSaysWhatIsKnown": True,
    }


def test_surface_namespace_fails_closed() -> None:
    assert parse_chat_surface_namespace({}).mode == "chat"
    assert parse_chat_surface_namespace({"surface_mode": "work", "context_id": "job-42"}).context_id == "job-42"
    assert (
        parse_chat_surface_namespace({"surface_mode": "workspace", "context_id": "workspace:virtual_office"}).context_id
        == "workspace:office"
    )
    assert (
        parse_chat_surface_namespace({"surface_mode": "workspace", "context_id": "workspace:canvas"}).context_id
        == "workspace:app_builder"
    )
    assert (
        parse_chat_surface_namespace({"surface_mode": "workspace", "context_id": "workspace:library"}).context_id
        == "workspace:my_stuff"
    )
    assert (
        parse_chat_surface_namespace({"surface_mode": "workspace", "context_id": "workspace:paper_trading"}).context_id
        == "workspace:paper_trading"
    )

    for payload in (
        {"surface_mode": "code"},
        {"surface_mode": "work"},
        {"surface_mode": "chat", "context_id": "job-42"},
        {"surface_mode": "chat", "context_id": "workspace:mission"},
        {"surface_mode": "workspace"},
        {"surface_mode": "workspace", "context_id": "mission"},
        {"surface_mode": "workspace", "context_id": "workspace:../settings"},
        {"surface_mode": "workspace", "context_id": "workspace:"},
        {"surface_mode": "workspace", "context_id": "workspace:not-a-real-route"},
    ):
        try:
            parse_chat_surface_namespace(payload)
        except ValueError:
            continue
        raise AssertionError(f"namespace should have failed closed: {payload}")


def test_workspace_sessions_cannot_cross_route_namespaces() -> None:
    mission = parse_chat_surface_namespace({"surface_mode": "workspace", "context_id": "workspace:mission"})
    office = parse_chat_surface_namespace({"surface_mode": "workspace", "context_id": "workspace:office"})
    meta = SessionMeta(session_id="resident", surface_mode="workspace", context_id="workspace:mission")

    assert session_namespace_matches(meta, mission)
    assert not session_namespace_matches(meta, office)
