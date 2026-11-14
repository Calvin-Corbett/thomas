(function () {
  'use strict';

  const MAX_LIVE_EVENTS = 120;
  // Code-Thomas wears the anvil — he builds (owner, 2026-08-10). Same glyph
  // as the events module's turn avatar; Chat keeps its own star.
  const CODE_ANVIL_SVG = '<svg viewBox="0 0 256 256" aria-hidden="true"><path d="M240 60h-92a12 12 0 0 0 0 24h6.6c-4 24.5-22.8 44-47 48.6C82.9 137.4 64 121.4 64 96V84h12a12 12 0 0 0 0-24H24a12 12 0 0 0 0 24h16v12c0 34.6 24.7 58.5 56 63.4v10.2c0 11-4.7 21.4-13 28.6l-18.9 16.5A12 12 0 0 0 72 236h112a12 12 0 0 0 7.9-21.1L173 198.4a38.2 38.2 0 0 1-13-28.6v-10.6c37.5-6 66.2-35 70.7-71.2H240a12 12 0 0 0 0-24Z"/></svg>';
  // Show the FULL running action feed (Codex-style: every reply/update lands
  // inline as it happens). Collapsing to 4 visible notes hid the run from the
  // owner — his words: "as it's going down in the chat, it's replying,
  // updating on things". The live-event ring above already bounds memory.
  const MAX_VISIBLE_PROGRESS_EVENTS = 120;
  const MAX_PROGRESS_EVENT_CHARS = 420;
  const NARRATIVE_EVENT_KINDS = new Set(['approval', 'disconnected', 'reconnected', 'done', 'final', 'insight', 'planning', 'say', 'settings', 'steering', 'stopped', 'stopping']);
  const state = {
    conversations: [], activeId: '', conversation: null, liveEvents: [], changes: [], tree: [], treeLoaded: false, treePath: '', artifacts: [], filePreview: null,
    pendingApproval: null, pendingRequest: null, lastContext: {}, running: false, runStartedAt: 0, runStatus: 'ready', source: null,
    // projectRoot is the folder of the conversation ON SCREEN; chosenProjectRoot
    // is the folder a person actually PICKED (dialog, project card, typed name)
    // and is the only root a new task may inherit. Conflating the two is how
    // task B was bound into task A's auto-made folder: viewing anything set
    // projectRoot, and the next new task treated that as a choice.
    finishing: null, approvalBusy: false, steeringBusy: false, projectRoot: '', chosenProjectRoot: '', chosenProjectPicked: false, projectNames: {}, terminalTool: '', contextEpoch: 0, runProof: null,
    pendingHistoryChoice: null, historyChoiceBusy: false,
    // 'pending' until the first history fetch answers, 'loaded' on an answer,
    // 'error' on a failure before any answer. The sidebar's terminal claim
    // "No code tasks yet." is only honest in the 'loaded' state -- ~197 real
    // tasks rendered under that claim while the first fetch was in flight.
    historyLoadState: 'pending',
    openingConversationId: '',
    runId: '', eventCursor: 0, retryRequest: null, drawerOpen: false, drawerWidth: 460, pendingUserText: '',
  };
  let adapterActive = false;
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const modes = () => window.ThomasUnifiedModes;
  const lifecycle = () => window.ThomasCodeLifecycle;
  // Siblings loaded ahead of this file by chat.html. Reached through accessors
  // rather than captured once, the same way lifecycle() is, so load order stays
  // the only ordering rule there is.
  const codeResults = () => window.ThomasCodeResults;
  const codeProjects = () => window.ThomasCodeProjects;
  const host = () => modes().host() || {};
  const surface = () => document.getElementById('tc-mode-surface');

  // The fallback names the action, the error names the cause, and a reader needs
  // both. Returning the cause alone -- which is what this did -- threw away every
  // one of the fourteen sentences the callers below pass in, because a server
  // error almost always carries *some* message. Opening a deleted task showed
  // "not found", twice, and never once said what had not been found; the author's
  // "Could not open that Build task." was written, passed in, and dropped.
  function errorText(error, fallback) {
    const reason = error instanceof Error && typeof error.message === 'string'
      ? error.message.trim()
      : '';
    if (!reason) return fallback;
    if (!fallback || reason === fallback) return reason;
    // A reason that already restates the action is not worth saying twice.
    if (reason.toLowerCase().includes(fallback.toLowerCase().replace(/[.!]+$/, ''))) return reason;
    return `${fallback.replace(/[.!\s]+$/, '')}: ${reason}`;
  }

  function isInternalResultPath(value) {
    const path = String(value || '').replace(/\\/g, '/').replace(/^\.\/+/, '').toLowerCase();
    return path === '.thomas' || path.startsWith('.thomas/') || path.includes('/.thomas/evolve/agent/');
  }

  // Hand the siblings the collaborators this file owns. One state object, one
  // escaper, one render -- injected rather than re-declared, so a split can
  // never become two copies that drift (the failure AGENTS.md calls out).
  codeResults().configure({ state, esc, isInternalResultPath, lifecycle, render, pushLiveEvent, safely, recordPreferenceWarning });
  codeProjects().configure({ state });

  // The workspace readers live in the results module, beside the drawer content
  // they fill. Bound to local names here so the call sites below read exactly as
  // they did when the functions were declared in this file -- and so the pair
  // stays one import list rather than a scattering of `codeResults().` calls.
  const {
    loadChanges, loadTree, loadFile, checkpointChanges, maybeAutoPlaytest,
  } = codeResults();

  // Which folder and which task this surface is pointed at -- creating a task,
  // picking its folder, switching away from one, and reattaching to a run that
  // is still going. That module owns the project chip and the surface snapshot
  // those answers are read from; this file owns the stream, the renderer and
  // the error reporting they need, and hands them over here. Everything below
  // calls them by the same names they had when they lived in this file.
  const {
    adoptOrphanRun, bindHistoryChoice, canSwitchContext, clearContextState, historyAskHtml,
    newConversation, pickProject, reattachRunFor, restoreProjectPreference,
  } = codeProjects().createTaskSession({
    closeSource, esc, finishBusy, host, lifecycle, loadConversation, loadTree, openStream,
    pushLiveEvent, recordError, recordPreferenceWarning, refresh, render, safely,
  });

  // One predicate for "what state did this run finish in", for BOTH the run you
  // are watching and the run that had already finished when `/send` answered.
  // There used to be two, and they disagreed: this one, and an inline
  // `persistence_confirmed === true ? (outcome || 'completed') : 'failed'` in
  // `acceptStartedRun`.
  //
  // The server builds ONE dict for a finished run
  // (evolve_agent_runtime._record_run_outcome) and sends it verbatim down both
  // routes -- in the SSE frame as `{type:'done', **persistence}` and in the
  // replayed `/send` body as `{**response, **persistence, run_state:...}`. The
  // two readings agreed on completed/noop/failed and split on exactly one
  // value: `outcome: 'conversation'`, the run where Thomas ANSWERS a question
  // without editing anything (`reason: "Thomas replied without changing files"`,
  // `ok: true`) -- which is what the "Look at the project I have selected, tell
  // me what it does" starter asks for. Watched, it read 'completed'. Replayed,
  // 'conversation' went straight into `state.runStatus`, where it is not a word
  // the label table knows, so `labels[...] || 'Ready'` fell through and the
  // activity bar said **Ready** about a run that had just finished, wearing an
  // `is-conversation` class no stylesheet defines.
  //
  // Derived from `persistence_confirmed`/`noop`/`ok` rather than from the
  // `outcome` word on purpose: those three cover every outcome the writer emits
  // (conversation and completed are both ok, persistence_failed is
  // !persistence_confirmed), and deriving means a NEW outcome word can never
  // leak into `state.runStatus` and blank the badge the same way.
  function terminalRunStatus(payload) {
    if (payload.persistence_confirmed !== true) return 'failed';
    if (payload.noop === true) return 'noop';
    return payload.ok === true ? 'completed' : 'failed';
  }

  function recordError(error, fallback) {
    pushLiveEvent({ type: 'error', text: errorText(error, fallback) });
    // Every user-visible Code failure also lands in the issue ledger report.
    try {
      void fetch('/api/issues', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ surface: 'code-ui', kind: 'action_error', message: errorText(error, fallback).slice(0, 300), context: { runId: state.runId || '' } }),
      }).catch(() => {});
    } catch (e) {}
    render();
  }

  function recordPreferenceWarning(error, message) {
    console.warn(`[Thomas Code] ${message}`, error);
  }

  async function safely(action, fallback) {
    try { return await action(); }
    catch (error) { recordError(error, fallback); return null; }
  }

  // Lifted into unified_code_events.js -- see the note at the top of that file.
  // These are const bindings now, not hoisted declarations, so nothing above this
  // line may *call* them at load time. Nothing does: lines 1-132 only declare.
  const {
    eventLabel, annotateTerminalEvent, eventType, isTechnicalEvent, eventHtml, finalReplyEvent, progressEvents,
    failureSummary, turnHtml, replyHtml, replyBlockHtml, elapsedLabel, transcriptEvents, transcriptText, flagExpectedProbe,
    interleavedActivityHtml, emptyStateHtml, copyReplyText,
  } = window.ThomasCodeEvents.create({
    MAX_VISIBLE_PROGRESS_EVENTS, MAX_PROGRESS_EVENT_CHARS, NARRATIVE_EVENT_KINDS, state, esc,
    codeResults, surface, isInternalResultPath, safely, pushLiveEvent, render, send,
  });
  const liveView = window.ThomasCodeLiveView.create({
    state, surface, isActive: () => adapterActive, render, loadFile, esc, MAX_LIVE_EVENTS, MAX_VISIBLE_PROGRESS_EVENTS, annotateTerminalEvent, flagExpectedProbe, eventType, eventHtml, isTechnicalEvent, progressEvents, finalReplyEvent, interleavedActivityHtml
  });
  // Pause, resume, messages to the run's agents, answers to its questions, and
  // the parts of the page that read them (the agents, the live cards, the
  // composer's queue, the header and the sidebar rows) -- unified_code_controls.js.
  if (!window.ThomasCodeControls) throw new Error('unified_code_controls.js must load before unified_code_mode.js');
  const controlsFeature = window.ThomasCodeControls.create({
    state, esc, host, render, safely, send, stopRun, steer, startNextQueued, pushLiveEvent,
    recordError, changeAction, surface, codeProjects, isInternalResultPath, transcriptText, isActive: () => adapterActive,
  });
  function transcriptScroller(...args) { return liveView.transcriptScroller(...args); }
  function scrollTranscriptToNewest(...args) { return liveView.scrollTranscriptToNewest(...args); }
  function updateRunStatus(...args) { return liveView.updateRunStatus(...args); }
  function refreshOpenPagePreview(...args) { return liveView.refreshOpenPagePreview(...args); }
  function pushLiveEvent(...args) { return liveView.pushLiveEvent(...args); }
  function trimLiveEventDom(...args) { return liveView.trimLiveEventDom(...args); }
  function appendLiveEvent(...args) { return liveView.appendLiveEvent(...args); }

  const surfaceFeature = window.ThomasCodeSurface.create({
    get CODE_ANVIL_SVG() { return CODE_ANVIL_SVG; },
    get adapterActive() { return adapterActive; }, set adapterActive(value) { adapterActive = value; },
    get approvePending() { return approvePending; },
    get bindHistoryChoice() { return bindHistoryChoice; },
    get changeAction() { return changeAction; },
    get checkpointChanges() { return checkpointChanges; },
    get codeProjects() { return codeProjects; },
    get codeResults() { return codeResults; },
    get controls() { return controlsFeature; },
    get copyReplyText() { return copyReplyText; },
    get emptyStateHtml() { return emptyStateHtml; },
    get esc() { return esc; },
    get eventLabel() { return eventLabel; },
    get eventType() { return eventType; },
    get failureSummary() { return failureSummary; },
    get finalReplyEvent() { return finalReplyEvent; },
    get historyAskHtml() { return historyAskHtml; },
    get host() { return host; },
    get interleavedActivityHtml() { return interleavedActivityHtml; },
    get isInternalResultPath() { return isInternalResultPath; },
    get loadFile() { return loadFile; },
    get loadTree() { return loadTree; },
    get progressEvents() { return progressEvents; },
    get pushLiveEvent() { return pushLiveEvent; },
    get replyHtml() { return replyHtml; },
    get replyBlockHtml() { return replyBlockHtml; },
    get safely() { return safely; },
    get send() { return send; },
    get state() { return state; },
    get stopRun() { return stopRun; },
    get surface() { return surface; },
    get transcriptScroller() { return transcriptScroller; },
    get turnHtml() { return turnHtml; },
  });

  const run_streamFeature = window.ThomasCodeRunStream.create({
    get adoptStartedConversation() { return adoptStartedConversation; },
    get appendLiveEvent() { return appendLiveEvent; },
    get clearContextState() { return clearContextState; },
    get codeProjects() { return codeProjects; },
    get codeResults() { return codeResults; },
    get controls() { return controlsFeature; },
    get errorText() { return errorText; },
    get host() { return host; },
    get lifecycle() { return lifecycle; },
    get loadConversation() { return loadConversation; },
    get maybeAutoPlaytest() { return maybeAutoPlaytest; },
    get pushLiveEvent() { return pushLiveEvent; },
    get refresh() { return refresh; },
    get render() { return render; },
    get safely() { return safely; },
    get scrollTranscriptToNewest() { return scrollTranscriptToNewest; },
    get send() { return send; },
    get state() { return state; },
    get terminalRunStatus() { return terminalRunStatus; },
    get updateRunStatus() { return updateRunStatus; },
    get waitForRestartReady() { return waitForRestartReady; },
  });
  function closeSource(...args) { return run_streamFeature.closeSource(...args); }

  function replacePendingApproval(data, request) {
    const retry = { ...request };
    delete retry.approval_id;
    state.pendingApproval = data.approval;
    state.pendingRequest = retry;
    state.runStatus = 'approval';
    pushLiveEvent({ type: 'approval', text: data.error || 'Fresh approval is required before Thomas can continue.' });
  }

  function adoptStartedConversation(conversationId, projectRoot, runId) {
    state.openingConversationId = '';
    if (state.activeId !== conversationId) {
      state.contextEpoch += 1;
      state.conversation = null;
      state.changes = [];
      state.tree = [];
      state.treePath = '';
      state.artifacts = [];
      state.filePreview = null;
      state.terminalTool = '';
      state.runProof = null;
    }
    state.activeId = conversationId;
    state.projectRoot = projectRoot || state.projectRoot;
    lifecycle().adoptRunIdentity(state, runId);
  }
  function acceptStartedRun(...args) { return run_streamFeature.acceptStartedRun(...args); }
  function render(...args) { return surfaceFeature.render(...args); }

  // An error body is rarely JSON. aiohttp answers an unregistered route with the
  // plain text "404: Not Found", and `response.json()` on that throws
  // "Unexpected non-whitespace character after JSON at position 3" -- it parses
  // 404 as a number and chokes on the colon. The owner saw exactly that string
  // and it told him nothing: the real fault was that Code's entire API had
  // failed to register. Report the situation, not the syntax error.
  async function readJson(response, what) {
    // The Node contract harness stubs a response that can only answer json();
    // a real browser response can do both. Prefer text() so a non-JSON error
    // body is readable, and fall back where text() does not exist.
    if (typeof response.text !== 'function') return response.json();
    const body = await response.text();
    try {
      return JSON.parse(body);
    } catch (parseError) {
      const detail = body.trim().slice(0, 120) || '(empty response)';
      if (response.status === 404) {
        throw new Error(`${what} is not available on this server (404). Thomas answered "${detail}" instead of data -- the Build API did not register. Restarting the server reloads its routes.`);
      }
      throw new Error(`${what} answered ${response.status} with something that is not data: "${detail}"`);
    }
  }

  async function refresh(options) {
    try {
      const response = await fetch('/api/evolve/agent/conversations?slim=1');
      const data = await readJson(response, 'Build history');
      if (!response.ok || !Array.isArray(data.conversations)) throw new Error(data.error || `Build history could not be refreshed (${response.status})`);
      state.conversations = data.conversations;
      state.historyLoadState = 'loaded';
      host().renderHistory && host().renderHistory();
      return true;
    } catch (error) {
      // A failure before any answer is an ERROR state, not an empty history.
      // A failure after a successful load keeps the loaded state: the rows on
      // screen are real, and recordError below already names the failure.
      if (state.historyLoadState !== 'loaded') state.historyLoadState = 'error';
      host().renderHistory && host().renderHistory();
      if (options && options.throwOnError) throw error;
      recordError(error, 'Build history could not be refreshed.');
      return false;
    }
  }

  function renderHistory(root, query) {
    const term = String(query || '').trim().toLowerCase();
    const rows = state.conversations.filter(row => Number(row.turn_count || 0) > 0 && (!term || String(row.title || '').toLowerCase().includes(term)));
    // "No code tasks yet." is a claim about the history, and before the first
    // fetch answers the history is UNKNOWN -- ~197 real tasks rendered under
    // that claim while the request was in flight. Same rule as the chat
    // sidebar: loading until the fetch answers, a named error when it fails,
    // and the terminal empty claim only once an answer confirmed it.
    const emptyMessage = state.historyLoadState === 'loaded'
      ? (term ? 'No matching code tasks.' : 'No code tasks yet.')
      : state.historyLoadState === 'error'
        ? 'Build tasks could not be loaded.'
        : 'Loading code tasks…';
    // The rows keep their elements while what they show is unchanged (unified_code_history_rows.js), so opening a
    // task changes two rows instead of rebuilding the whole list.
    window.ThomasCodeHistoryRows.render(root, rows, { state, controls: controlsFeature, history: window.ThomasSidebarHistory, esc, emptyMessage, term, open: id => { void safely(() => loadConversation(id), 'Could not open that Build task.'); } });
  }

  async function loadConversation(id, options) {
    const internal = options && options.internal === true;
    if (!internal && !canSwitchContext()) return false;
    const epoch = internal ? Number(options.epoch) : state.contextEpoch + 1;
    if (!internal) state.contextEpoch = epoch;
    if (internal && (id !== state.activeId || epoch !== state.contextEpoch)) return false;
    if (!internal) {
      state.openingConversationId = id;
      // Only what changes shimmers; the screen is drawn once, when the task's content is here (unified_code_loading.js).
      if (!(window.ThomasCodeLoading && window.ThomasCodeLoading.show())) render();
    }
    let data;
    try {
      const response = await fetch(`/api/evolve/agent/conversations/${encodeURIComponent(id)}`);
      data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || `Build task could not be loaded (${response.status})`);
    } catch (error) {
      if (!internal && epoch === state.contextEpoch) {
        state.openingConversationId = '';
        render();
      }
      throw error;
    }
    if (epoch !== state.contextEpoch) return false;
    if (!internal) clearContextState();
    state.openingConversationId = '';
    state.activeId = id;
    state.conversation = data.conversation;
    state.projectRoot = data.conversation.project_root || state.projectRoot;
    // Show the resolved task and folder before filesystem discovery finishes.
    codeProjects().updateProjectButton();
    const token = lifecycle().contextToken(state);
    if (!(options && options.deferRender)) render();
    if (!internal) scrollTranscriptToNewest();
    await Promise.all([
      loadChanges({ token, deferRender: true }), loadTree('', { token, deferRender: true }),
      internal ? Promise.resolve() : reattachRunFor(id),
    ]);
    if (!lifecycle().contextMatches(state, token)) return false;
    // The changes and the file tree live in the drawer and the viewer; with both closed only the top bar needs them.
    if (!(options && options.deferRender)) { if (state.drawerOpen || (state.viewer && state.viewer.file)) render(); else window.ThomasCodeHeader && window.ThomasCodeHeader.paint(); }
    // Only on a real open. `internal` reloads run underneath a live run, and
    // yanking the scroller then would fight someone reading back through it.
    if (!internal) scrollTranscriptToNewest();
    // Results become visible on arrival rather than after a click.
    void codeResults()
      .hydrateArtifactThumbnails()
      .then(() => { if (!internal) scrollTranscriptToNewest(); })
      .catch(() => {});
    host().renderHistory && host().renderHistory();
    if (!internal) {
      // A task queued for THIS conversation while it was parked starts now.
      if (!state.running) startNextQueued();
    }
    return true;
  }

  async function send(message, context, options) {
    if (state.approvalBusy) throw new Error('A Build approval is in progress. Resolve it before starting another task.');
    // While Thomas is asking you something, what you TYPE is your answer (a Fix
    // it or playtest click is not); an answer that failed stays in the composer.
    const answered = options && options.typed ? await controlsFeature.answerTyped(message) : false;
    if (answered) return answered === true;
    // Codex-parity queue: sending while THIS conversation's run is going
    // queues the task and auto-starts it when the current run's result is
    // durable. Only the TARGET conversation being busy queues. A send with no
    // conversation on screen starts below as its own new conversation (the
    // server creates one). Queueing it was the misdelivery: the entry carried cid:''
    // and startNextQueued fired it into whichever conversation was ACTIVE
    // when the live run finished -- measured 2026-08-05: a countdown task sent
    // while the Bitcoin run was live appended to that conversation and
    // OVERWROTE the finished Bitcoin deliverable with a countdown page.
    if ((state.running || state.finishing) && state.activeId) {
      state.queuedSends = state.queuedSends || [];
      // Stamp the conversation at ENQUEUE time — with parallel runs the user
      // may switch away, and a queued task must fire into ITS conversation. It
      // waits above the composer with Steer and ✕ (the id is theirs to name).
      state.queuedSends.push({ id: `q${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, message: String(message || ''), context: context || state.lastContext || {}, cid: state.activeId, at: Date.now() });
      render();
      return true;
    }
    state.lastContext = context || state.lastContext || {};
    // Echoed by the transcript until the server's copy of this turn arrives.
    // Not set for a steer: `preserveProgress` means the run is continuing and the
    // steering text belongs in the activity feed, not as a new message bubble.
    if (!(options && options.preserveProgress)) { state.pendingUserText = String(message || ''); window.ThomasAttachmentStrip?.stage(state, message, context); }
    state.running = true;
    state.runStatus = 'working';
    if (!(options && options.preserveProgress) || !state.runStartedAt) state.runStartedAt = Date.now();
    state.terminalTool = '';
    host().setBusy && host().setBusy(true);
    // A new run starts with an empty feed: its head says "working" and the status
    // line above the composer "Thomas is starting" until the first frame lands.
    if (options && options.preserveProgress) pushLiveEvent({ type: 'planning', text: 'Thomas is restarting with your steering update…' });
    else state.liveEvents = [];
    if (!(options && options.preserveProgress)) state.artifacts = [];
    render();
    let requestBody = null;
    try {
      requestBody = lifecycle().runRequest(state, message, state.lastContext);
      const epoch = state.contextEpoch;
      const { response, data, stopped } = await lifecycle().postRun(requestBody, { notice: text => pushLiveEvent({ type: 'planning', text }), alive: () => state.running && state.contextEpoch === epoch });
      if (stopped) return false;
      if (response.status === 409 && data.code === 'execution_settings_blocked') {
        state.retryRequest = null; state.runStatus = 'blocked'; state.runStartedAt = 0;
        state.liveEvents = [{ type: 'settings', text: data.error }];
        finishBusy(); render(); return false;
      }
      if (response.status === 409 && data.code === 'approval_required') {
        replacePendingApproval(data, requestBody); finishBusy(); render(); return false;
      }
      if (response.status === 409 && data.code === 'project_is_thomas_source' && window.ThomasSelfEdit?.startFromChat) {
        finishBusy(); state.runStatus = ''; await window.ThomasSelfEdit.startFromChat(message); return true;
      }
      if (!response.ok || !data.ok) throw new Error(data.error || `Build request failed (${response.status})`);
      if (
        !requestBody.conversation_id && requestBody.project_root && !requestBody.project_choice && data.project_root
        && codeProjects().projectNameKey(data.project_root) !== codeProjects().projectNameKey(requestBody.project_root)
      ) {
        // Same healing as newConversation: the server declined a restored
        // leftover root and assigned this task its own folder.
        state.chosenProjectRoot = '';
        state.chosenProjectPicked = false;
        try {
          localStorage.removeItem('thomas_code_project_root');
          localStorage.removeItem('thomas_code_project_label');
        } catch (cleanupError) { recordPreferenceWarning(cleanupError, 'The declined project root could not be cleared.'); }
      }
      return await acceptStartedRun(data);
    } catch (error) {
      if (requestBody) state.retryRequest = requestBody;
      pushLiveEvent({ type: 'error', text: errorText(error, 'Build request failed.') });
      state.runStatus = 'failed';
      finishBusy();
      render();
      return false;
    }
  }
  function openStream(...args) { return run_streamFeature.openStream(...args); }
  function handleStreamError(...args) { return run_streamFeature.handleStreamError(...args); }
  function finishBusy(...args) { return run_streamFeature.finishBusy(...args); }
  function finishRun(...args) { return run_streamFeature.finishRun(...args); }
  function startNextQueued(...args) { return run_streamFeature.startNextQueued(...args); }
  function steer(...args) { return run_streamFeature.steer(...args); }
  async function changeAction(action, file, approvalId, options) {
    const token = lifecycle().contextToken(state);
    if (!token.id) throw new Error('Open a Build conversation before changing files.');
    const body = lifecycle().changeRequest(action, file, token.id, approvalId, options && options.requestId);
    const response = await fetch(`/api/evolve/agent/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!lifecycle().contextMatches(state, token)) return false;
    if (response.status === 409 && data.code === 'approval_required') {
      replacePendingApproval(data, { kind: 'change', action, file, request_id: body.request_id });
      if (!(options && options.deferRender)) render();
      return false;
    }
    if (!response.ok || !data.ok) {
      state.runStatus = 'failed';
      throw new Error(data.error || `${action} failed (${response.status})`);
    }
    state.runStatus = 'completed';
    pushLiveEvent({ type: 'meta', text: `${action === 'revert' ? 'Reverted' : 'Kept'} ${file}.` });
    await loadChanges({ token, deferRender: true });
    // Reverting a NEW file deletes it, and only `loadChanges` was re-read -- so
    // the drawer's Files list went on offering a file that no longer existed.
    // Measured: after Approve the change row cleared, the tree still listed
    // `scratchpad.html`, and the server said `entries: []` with the artifact
    // route answering 404.
    //
    // The current folder is preserved so a revert does not also walk the reader
    // back to the project root.
    //
    // Its failure is reported on its own rather than thrown: the revert has
    // already succeeded by this point, and letting a stale-list problem reject
    // here would report a change that happened as one that did not.
    await loadTree(state.treePath || '', { token, deferRender: true })
      .catch(error => recordError(error, 'The file list could not be refreshed.'));
    if (!(options && options.deferRender)) render();
    return true;
  }
  async function approvePending() {
    if (!state.pendingApproval || !state.pendingRequest || state.approvalBusy) return false;
    const approval = state.pendingApproval;
    const pending = { ...state.pendingRequest };
    state.approvalBusy = true;
    render();
    try {
      if (!pending.approval_id) {
        const approved = await fetch('/api/evolve/agent/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ approval_id: approval.id }) });
        const data = await approved.json();
        if (!approved.ok || !data.ok) throw new Error(data.error || 'Approval failed.');
        pending.approval_id = approval.id;
        state.pendingRequest = pending;
      }
      if (pending.kind === 'change') {
        const applied = await changeAction(pending.action, pending.file, pending.approval_id, { deferRender: true, requestId: pending.request_id });
        if (!applied) return false;
      } else {
        state.running = true;
        state.runStartedAt = Date.now();
        state.runStatus = 'working';
        host().setBusy && host().setBusy(true);
        const response = await fetch('/api/evolve/agent/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(pending) });
        const started = await response.json();
        if (response.status === 409 && started.code === 'approval_required') {
          replacePendingApproval(started, pending);
          finishBusy();
          return false;
        }
        if (!response.ok || !started.ok) throw new Error(started.error || 'Approved Build task could not start.');
        await acceptStartedRun(started);
      }
      state.pendingApproval = null;
      state.pendingRequest = null;
      return true;
    } catch (error) {
      finishBusy();
      state.pendingApproval = approval;
      state.pendingRequest = pending;
      state.runStatus = 'approval';
      pushLiveEvent({ type: 'error', text: errorText(error, 'Approval could not be completed.') });
      return false;
    } finally {
      state.approvalBusy = false;
      render();
    }
  }
  async function waitForRestartReady(runId = state.runId) {
    // Per-run status: another task may be running while this one stops.
    const statusUrl = `/api/evolve/agent/status?run_id=${encodeURIComponent(runId)}`;
    for (let attempt = 0; attempt < 50; attempt += 1) {
      const response = await fetch(statusUrl);
      const status = await response.json().catch(() => null);
      // status.ok describes the LAST RUN's outcome, not endpoint health — a
      // steering-stopped run always reports ok:false (killed, returncode 1),
      // which must not abort the restart. A missing slot is also no longer active.
      if (response.status === 404 && status?.code === 'run_not_found' && status.run_id === runId) return true;
      if (!response.ok || !status) throw new Error((status && status.error) || 'Steering status check failed.');
      if (status.running === false && status.recording !== true) return true;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error('Thomas is still stopping the previous run. The steering update was not applied; retry it.');
  }
  // Codex-parity interrupt: stop the running turn on demand. Changed files
  // stay in the workspace with Keep/Revert, so stopping is never destructive.
  //
  // The ONE stop routine. There used to be two -- this one behind the drawer's
  // Stop button, and a second `stop()` behind the mode adapter -- with different
  // wording ("Build task stopped (process exit N)" vs the sentence below) and
  // different behavior (the adapter one ran finishRun, this one refreshed
  // nothing). Which stop a user got depended on which button they happened to
  // press. Both entry points now land here; the honest wording and the refresh
  // travel with every stop.
  async function stopRun() {
    if (!state.running || state.steeringBusy) return false;
    state.steeringBusy = true;
    render();
    try {
      const response = await fetch('/api/evolve/agent/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: state.runId }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok && response.status !== 202) throw new Error(data.error || 'Stop failed.');
      // The stop is requested but not yet confirmed. The badge says so, and if
      // the confirmation poll below times out, the stream's `done` handler
      // reads this status (`stopWasPending`) and still files the run as
      // stopped rather than failed.
      state.runStatus = 'stopping';
      updateRunStatus();
      await waitForRestartReady();
      closeSource();
      pushLiveEvent({ type: 'stopped', text: state.conversation?.self_edit ? 'Stopped — private changes were retained for review. Your running version was not changed.' : 'Stopped — you interrupted this run. Anything already changed is in Outputs with Keep/Revert.' });
      state.runStatus = 'stopped';
      finishBusy();
      // The sentence above points at Outputs, and Outputs used to be stale: a
      // stopped run never re-read changes or the tree, so FILES sat on
      // "Loading files…" and CHANGED FILES was absent until the user switched
      // away and back -- measured live, on every drawer stop. Same shape as
      // the post-Keep/Revert path: reload both, report a reload failure on its
      // own rather than throwing, because the stop itself has already
      // succeeded and must not be reported as one that failed.
      const token = lifecycle().contextToken(state);
      if (token.id) {
        if (state.conversation?.self_edit) {
          await loadConversation(token.id, { internal: true, epoch: token.epoch, deferRender: true })
            .catch(error => recordError(error, 'The retained self-edit result could not be refreshed.'));
        }
        await loadChanges({ token, deferRender: true })
          .catch(error => recordError(error, 'The changed files could not be refreshed after the stop.'));
        await loadTree(state.treePath || '', { token, deferRender: true })
          .catch(error => recordError(error, 'The file list could not be refreshed after the stop.'));
      }
      startNextQueued();
      return true;
    } finally {
      state.steeringBusy = false;
      render();
    }
  }
  // The run's clock lives in the status line above the composer (its own 1 s
  // paint, unified_code_live_view.js); this one keeps the agents' times, the
  // live diff and the message poll current.
  if (window.setInterval) window.setInterval(() => controlsFeature.tick(), 1000);
  // Jump-to-latest: the button shows whenever the transcript is scrolled away
  // from the newest content, and one click returns there (owner, 2026-08-10:
  // "there is no scroll-to-bottom so I have to drag the scroll thing").
  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('click', event => {
      const hit = event.target instanceof Element ? event.target.closest('[data-code-jump-bottom]') : null;
      if (hit) {
        // Hide NOW - the visibility interval re-shows it if the jump
        // genuinely did not land. A third late jump absorbs thumbnails
        // that hydrate and grow the transcript after the first two.
        hit.hidden = true;
        scrollTranscriptToNewest();
        window.setTimeout(scrollTranscriptToNewest, 450);
      }
    });
    if (window.setInterval) window.setInterval(() => {
      const root = surface(); if (!root) return;
      const jump = root.querySelector('[data-code-jump-bottom]'); if (!jump) return;
      const transcript = transcriptScroller(root); if (!transcript) return;
      const away = transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight > 220;
      jump.hidden = !away;
    }, 700);
  }
  restoreProjectPreference();
  codeResults().restoreDrawerWidth();

  async function leave() {
    adapterActive = false;
    // Hand the composer back to Chat's own rail. The CSS is scoped to
    // `[data-surface-mode="code"]` so a leftover flag would be inert, but a
    // stale attribute is a lie about what is on screen.
    const shell = document.getElementById('tc-shell');
    if (shell) {
      delete shell.dataset.codeSide;
      shell.style.removeProperty('--tc-code-drawer-width');
    }
    codeProjects().updateProjectButton();
    controlsFeature.leave();
  }

  modes().registerAdapter('code', {
    enter: () => { adapterActive = true; codeProjects().updateProjectButton(); render(); void codeProjects().loadProjectNames(); void safely(adoptOrphanRun, 'Could not reconnect to the active Build run.'); },
    leave,
    refresh,
    renderHistory,
    newConversation: (projectRoot, projectLabel, options) =>
      safely(() => newConversation(projectRoot, projectLabel, options), 'Could not create the Build task.'),
    pickProject: () => safely(pickProject, 'Could not choose the project folder.'),
    send: (message, context) => safely(() => send(message, context, { typed: true }), 'The Build task failed unexpectedly.'),
    // The same routine as the drawer's Stop button -- see stopRun. Two stop
    // functions is how the two controls came to speak and behave differently.
    stop: () => { void safely(() => stopRun(), 'Could not stop the Build task.'); },
    isBusy: () => state.running || Boolean(state.finishing),
  });

  // Redesign hands a change off to Code by opening the thread it just created.
  // Exposed here because this module owns Code conversations; the alternative
  // was a full page reload through the ?forge_code= deep link.
  const conversationOpens = new Map();
  let latestConversationOpen = '';
  window.ThomasCodeMode = {
    conversationId: () => state.activeId || '',
    // The composer's primary button (chat_message_view.js / chat_shell_bindings.js).
    runControls: () => controlsFeature.runControls(),
    primaryAction: () => controlsFeature.primaryAction(),
    stopRun: () => controlsFeature.stopLive(),  // Escape in an empty composer; false when nothing is live
    openConversation: async (cid, options) => {
      const navigation = window.ThomasWorkspaceNavigation;
      if (!(options && options.withinTab) && navigation) {
        return navigation.openCode(cid);
      }
      const id = String(cid);
      // Share only the same pending selection. Revisiting A after B needs a
      // new owner, even while the first A response is still on the wire.
      const pending = conversationOpens.get(id);
      if (pending && latestConversationOpen === id && pending.epoch === state.contextEpoch) return pending.promise;
      latestConversationOpen = id;
      const owner = { epoch: state.contextEpoch, promise: null };
      const opening = (async () => {
        await modes().setMode('code');
        const loading = loadConversation(id);
        owner.epoch = state.contextEpoch;
        const loaded = await safely(() => loading, 'Could not open that Build task.');
        if (loaded === false || loaded === null) throw new Error('Could not open that Build task.');
        return document;
      })();
      owner.promise = opening;
      conversationOpens.set(id, owner);
      try { return await opening; }
      finally { if (conversationOpens.get(id) === owner) conversationOpens.delete(id); }
    },
  };

  // A deliverable's deep link is minted as `/?forge_code=<cid>` in
  // thomas/forge/anvil/forge_code_deliverables.py, and until now nothing on `/`
  // read it. The only consumer lived in the split runtime, which is pulled by
  // index.html -- served at `/classic`, not at `/`. So My Stuff's "Open Source
  // Chat" button, which navigates the top frame straight to that link
  // (static/my_stuff.script01.js), dropped the reader on a blank Chat surface
  // with the parameter still sitting in the URL and no hint that anything had
  // been asked for. Verified before the fix: `/?forge_code=<real cid>` landed in
  // Chat mode with no active conversation and zero turns.
  //
  // Handled in this module because it owns Code conversations, and only on boot
  // -- consuming the parameter on every render would reopen the task each time
  // the surface repainted.
  //
  // /classic keeps its own consumer: it is a separate page that still works when
  // reached directly, not a second copy racing this one on the same surface.
  function openDeepLinkedConversation() {
    let cid = '';
    try { cid = new URLSearchParams(location.search).get('forge_code') || ''; }
    catch (_error) { return; }
    if (!cid) return;

    // Strip the parameter BEFORE opening. If the task cannot be loaded the reader
    // should be left on an ordinary surface, not on a URL that replays the
    // failure on every refresh.
    try {
      const url = new URL(location.href);
      url.searchParams.delete('forge_code');
      history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    } catch (_error) { /* a stale URL is survivable; failing to open is not */ }

    void safely(() => window.ThomasCodeMode.openConversation(cid, { withinTab: true }),
      'Could not open that Build task.');
  }

  // This file is a classic script in <head>-order, so it runs before chat.html's
  // inline boot calls ThomasUnifiedModes.connect(). Waiting for DOMContentLoaded
  // is what guarantees setMode has a connected host to switch.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', openDeepLinkedConversation, { once: true });
  } else {
    openDeepLinkedConversation();
  }
})();
