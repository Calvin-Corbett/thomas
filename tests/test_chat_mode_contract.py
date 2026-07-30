from __future__ import annotations

import json
import subprocess
from pathlib import Path

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
CODE_RESULTS_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_results.js"
CODE_PROJECTS_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_projects.js"
CODE_SIBLING_JS = (CODE_RESULTS_JS, CODE_PROJECTS_JS)
CODE_LIFECYCLE_HARNESS = REPO_ROOT / "tests" / "web_node" / "unified_code_mode_lifecycle.mjs"
WORK_SUPPORT_HARNESS = REPO_ROOT / "tests" / "web_node" / "unified_work_support_lifecycle.mjs"
CHAT_MARKDOWN_HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_markdown_renderer.mjs"
CHAT_ANNOUNCEMENT_HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_completion_announcement_retry.mjs"


def test_primary_chat_has_accessible_three_mode_selector_above_search() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    selector = text.index('id="tc-mode-switch"')
    search = text.index('id="tc-search"')
    assert selector < search
    assert text.count('data-thomas-mode="chat"') == 1
    assert text.count('data-thomas-mode="code"') == 1
    assert text.count('data-thomas-mode="work"') == 1
    assert 'role="tablist"' in text
    assert 'aria-selected="true"' in text


def test_primary_chat_loads_real_mode_adapters_not_classic_iframes() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

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
    for sibling in ("unified_code_lifecycle.js", "unified_code_results.js", "unified_code_projects.js"):
        assert text.index(f"/static/js/{sibling}") < text.index("/static/js/unified_code_mode.js")


def test_chat_busy_transitions_refresh_shared_mode_chrome() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "state.streaming = true; setExternalBusy();" in text
    assert (
        "state.streaming = false; abortController = null;\n        updateStreamingBubble(idx); renderActivity(idx); setExternalBusy();"
        in text
    )


def test_verified_artifacts_offer_explicit_attachment_downloads() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "function artifactDownloadUrl(url)" in text
    assert "data-artifact-download" in text
    assert "download=1" in text


def test_primary_modes_do_not_duplicate_legacy_forge_or_workforce_navigation() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")
    workspace_list = text[text.index("const workspaces = [") : text.index("];", text.index("const workspaces = ["))]

    assert "label: 'Forge'" not in workspace_list
    assert "label: 'Workforce'" not in workspace_list


def test_primary_chat_cancel_button_requests_durable_session_scoped_cancellation() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "async function requestTaskCancel(sessionId, executionId)" in text
    assert "'/delegations/' + encodeURIComponent(executionId) + '/cancel'" in text
    assert "Promise.allSettled(executionIds.map(id => requestTaskCancel" in text
    assert "payload.ok !== true" in text
    assert "unreadable cancellation response" in text
    assert "catch (error) { payload = {}; }" not in text
    assert "there is no direct cancel endpoint yet" not in text


def test_primary_chat_renders_honest_tool_and_observed_model_receipts() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "finishToolStep(idx, evt.ok !== false)" in text
    assert "function applyModelRuntimeReceipt(idx, runtime)" in text
    assert "type === 'model_runtime'" in text
    assert "fallback used" in text
    assert "Verified: this model produced this reply" in text
    assert "const observedId =" in text


def test_primary_chat_renders_safe_structured_markdown_for_assistant_only() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "let html = isUser ? esc(m.text) : mdToHtml(m.text);" in text
    assert "tc-bubble${isUser ? '' : ' tc-markdown'}" in text
    # The markdown rules moved with the rest of the shell's inline CSS into
    # chat_shell.css; the class the renderer emits still has to be styled.
    assert ".tc-markdown h1, .tc-markdown h2, .tc-markdown h3" in CHAT_SHELL_CSS.read_text(encoding="utf-8")
    assert "html += '<pre><code>' + esc(code.join('\\n')) + '</code></pre>'" in text
    assert 'target="_blank" rel="noopener noreferrer"' in text

    completed = subprocess.run(
        ["node", str(CHAT_MARKDOWN_HARNESS), str(CHAT_HTML)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"userLiteral":true' in completed.stdout
    assert '"escapedHtml":true' in completed.stdout


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


def test_work_styles_are_decomposed_and_loaded_in_order() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

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
    text = CODE_JS.read_text(encoding="utf-8") + CODE_LIFECYCLE_JS.read_text(encoding="utf-8")
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
    text = CODE_JS.read_text(encoding="utf-8")

    assert "async function safely(action, fallback)" in text
    assert "void safely(stop" in text
    assert "void safely(() => loadTree" in text
    assert "void safely(() => loadFile" in text
    assert "void safely(approvePending" in text
    assert "void safely(() => steer" in text
    # newConversation takes a project root and label (the library picker names
    # what it chose), so match the containment rather than a zero-argument form.
    assert "safely(() => newConversation(projectRoot, projectLabel)" in text
    assert "send: (message, context) => safely(() => send(message, context)" in text
    assert "Promise.allSettled" in text


def test_code_adapter_preserves_terminal_stream_states() -> None:
    text = CODE_JS.read_text(encoding="utf-8")

    assert "state.source !== source" in text
    assert "state.runStatus = terminalRunStatus(payload)" in text
    assert "state.runStatus = 'disconnected'" in text
    assert "state.runStatus = 'stopped'" in text
    assert "payload.termination_confirmed !== true" in text
    assert "state.runStatus = 'stopping'" in text
    assert "const stopWasPending = state.runStatus === 'stopping'" in text
    assert "Stop confirmed (process exit ${payload.returncode})" in text
    assert "process exit ${payload.returncode}" in text
    assert "loadConversation(id, { internal: true, epoch, deferRender: true })" in text
    assert "approvalBusy" in text
    assert "steeringBusy" in text
    leave_body = text[text.index("async function leave()") : text.index("modes().registerAdapter('code'")]
    assert "closeSource()" not in leave_body
    assert "finishBusy()" not in leave_body
    assert "adapterActive = false" in leave_body


def test_code_adapter_collapses_terminal_and_tool_evidence_behind_details() -> None:
    text = CODE_JS.read_text(encoding="utf-8")
    css = (REPO_ROOT / "thomas/server/web/css/unified_code_activity.css").read_text(encoding="utf-8")

    assert "function isTerminalTool(name)" in text
    assert "function annotateTerminalEvent(event, tracker)" in text
    assert "function groupedTechnicalEvents(events)" in text
    assert "function technicalActivityHtml(events, saved)" in text
    assert '<details class="tc-code-saved-activity' in text
    assert '<div class="tc-code-technical' in text
    assert '<details class="tc-code-technical' not in text
    assert "Ran terminal command" in text
    assert "Read terminal result" in text
    assert "Worked through" in text
    assert "tc-code-tech-count" in text
    assert ".tc-code-technical-log" in css
    assert ".tc-code-technical code" in css
    assert "function projectActionsHtml()" not in text
    assert "data-code-drawer-close" in text
    assert "Build a game" not in text
    assert "Show details" in text


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
    classList: { add: () => {} },
    addEventListener: () => {},
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
    text = CODE_JS.read_text(encoding="utf-8")

    assert "function transcriptEvents(turn)" in text
    assert "JSON.parse(line)" in text
    assert "parsed && parsed.fc" in text
    assert "const events = transcriptEvents(turn)" in text
    assert "technicalActivityHtml(technicalEvents, true)" in text
    assert "tc-code-saved-activity" in text
    assert 'data-saved="true"' in text


def test_code_surface_uses_chat_conversation_with_collapsible_activity_drawer() -> None:
    text = CODE_JS.read_text(encoding="utf-8")
    css = (REPO_ROOT / "thomas/server/web/css/unified_code_mode.css").read_text(encoding="utf-8")
    html = (REPO_ROOT / "thomas/server/web/chat.html").read_text(encoding="utf-8")

    assert "tc-mode-hero" not in text
    assert "Build with Thomas" not in text
    assert 'class="tc-code-context"' in text
    assert "data-code-results-jump" in text
    assert "state.drawerOpen = !state.drawerOpen" in text
    assert "data-code-drawer-close" in text
    assert 'class="tc-code-project"' not in text
    assert 'aria-label="Code conversation"' in text
    assert 'id="tc-code-live-technical"' in text
    assert 'aria-label="Code activity"' in text
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


def test_chat_completion_announcement_retries_until_durably_reported() -> None:
    html = (REPO_ROOT / "thomas/server/web/chat.html").read_text(encoding="utf-8")

    assert "function queueCompletionAnnouncement(step, eid, attempt = 0)" in html
    assert "queueCompletionAnnouncement(s, rid)" in html
    assert "step._announced = true" in html
    assert "setTimeout(() =>" in html
    assert "queueCompletionAnnouncement(step, eid, attempt + 1)" in html
    assert "d.skipped === 'already_reported'" in html
    assert "Thomas completion announcement remains retryable" in html

    completed = subprocess.run(
        ["node", str(CHAT_ANNOUNCEMENT_HARNESS), str(CHAT_HTML)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr


def test_code_stream_preserves_steering_and_updates_activity_incrementally() -> None:
    text = CODE_JS.read_text(encoding="utf-8")
    stream_handler = text[text.index("source.onmessage = event =>") : text.index("source.onerror = () =>")]

    assert "function captureRenderState(root)" in text
    assert "function restoreRenderState(root, saved)" in text
    assert "steerValue" in text and "setSelectionRange" in text
    assert "function appendLiveEvent(event, replaceLast)" in text
    assert "appendLiveEvent(payload, replaced)" in stream_handler
    assert "render();" not in stream_handler


def test_code_revert_approval_is_presented_and_retried_with_receipt() -> None:
    text = CODE_JS.read_text(encoding="utf-8")

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
