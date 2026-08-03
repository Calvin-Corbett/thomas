(function () {
  'use strict';

  const MAX_LIVE_EVENTS = 120;
  // Show the FULL running action feed (Codex-style: every reply/update lands
  // inline as it happens). Collapsing to 4 visible notes hid the run from the
  // owner — his words: "as it's going down in the chat, it's replying,
  // updating on things". The live-event ring above already bounds memory.
  const MAX_VISIBLE_PROGRESS_EVENTS = 120;
  const MAX_PROGRESS_EVENT_CHARS = 420;
  const NARRATIVE_EVENT_KINDS = new Set(['approval', 'disconnected', 'done', 'final', 'insight', 'planning', 'say', 'steering', 'stopped', 'stopping']);
  const state = {
    conversations: [], activeId: '', conversation: null, liveEvents: [], changes: [], tree: [], treeLoaded: false, treePath: '', artifacts: [], filePreview: null,
    pendingApproval: null, pendingRequest: null, lastContext: {}, running: false, runStartedAt: 0, runStatus: 'ready', source: null,
    finishing: null, approvalBusy: false, steeringBusy: false, projectRoot: '', projectNames: {}, terminalTool: '', contextEpoch: 0, runProof: null,
    pendingHistoryChoice: null, historyChoiceBusy: false,
    runId: '', eventCursor: 0, retryRequest: null, drawerOpen: false, drawerWidth: 360, pendingUserText: '',
  };
  let adapterActive = false;
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const clampDrawerWidth = value => Math.max(280, Math.min(520, value));
  const modes = () => window.ThomasUnifiedModes;
  const lifecycle = () => window.ThomasCodeLifecycle;
  // Siblings loaded ahead of this file by chat.html. Reached through accessors
  // rather than captured once, the same way lifecycle() is, so load order stays
  // the only ordering rule there is.
  const codeResults = () => window.ThomasCodeResults;
  const codeProjects = () => window.ThomasCodeProjects;
  const host = () => modes().host() || {};
  const surface = () => document.getElementById('tc-mode-surface');

  function errorText(error, fallback) {
    return error instanceof Error && error.message ? error.message : fallback;
  }

  function isInternalResultPath(value) {
    const path = String(value || '').replace(/\\/g, '/').replace(/^\.\/+/, '').toLowerCase();
    return path === '.thomas' || path.startsWith('.thomas/') || path.includes('/.thomas/evolve/agent/');
  }

  // Hand the siblings the collaborators this file owns. One state object, one
  // escaper, one render -- injected rather than re-declared, so a split can
  // never become two copies that drift (the failure AGENTS.md calls out).
  codeResults().configure({ state, esc, isInternalResultPath, lifecycle, render });
  codeProjects().configure({ state });

  async function copyReplyText(text, button) {
    const value = String(text || '');
    let copied = false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
        copied = true;
      }
    } catch (_error) { copied = false; }
    if (!copied) {
      const area = document.createElement('textarea');
      area.value = value;
      area.setAttribute('readonly', '');
      area.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;';
      document.body.appendChild(area);
      area.select();
      try { copied = document.execCommand('copy'); } catch (_error) { copied = false; }
      area.remove();
    }
    if (button) {
      const icon = button.querySelector('i');
      button.title = copied ? 'Copied' : 'Copy failed';
      button.setAttribute('aria-label', button.title);
      if (icon && copied) icon.className = 'ph ph-check';
      setTimeout(() => {
        button.title = 'Copy reply';
        button.setAttribute('aria-label', 'Copy reply');
        if (icon) icon.className = 'ph ph-copy';
      }, 1400);
    }
    return copied;
  }

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
    eventLabel, annotateTerminalEvent, eventType, isTechnicalEvent, refreshElapsed, eventHtml,
    finalReplyEvent, progressEvents, failureSummary, turnHtml, replyHtml,
    elapsedLabel, narrativeActivityHtml, technicalActivityHtml, transcriptEvents,
  } = window.ThomasCodeEvents.create({
    MAX_VISIBLE_PROGRESS_EVENTS, MAX_PROGRESS_EVENT_CHARS, NARRATIVE_EVENT_KINDS, state, esc,
    codeResults, surface, isInternalResultPath, safely, pushLiveEvent, render, send,
  });
  function transcriptScroller(root) {
    const transcript = root.querySelector('.tc-code-transcript');
    const layout = root.querySelector('.tc-code-layout');
    if (layout && transcript && layout.scrollHeight > layout.clientHeight && transcript.scrollHeight <= transcript.clientHeight) return layout;
    return transcript;
  }

  // Arrive at the newest turn, not the oldest.
  //
  // A Code transcript that overflows its surface opened at scrollTop 0, so the
  // run report -- the newest thing on the page and the whole answer to "did it
  // work" -- sat below the fold and had to be hunted for. Measured on a real
  // conversation: 702px of unscrolled overflow with the verdict card at y=1419
  // inside an 868px scroller, identically via the sidebar click and the deep
  // link. Short transcripts were already right, because `margin-top:auto` pins
  // them to the bottom, which is exactly why this only bit the long ones and
  // went unnoticed.
  //
  // Runs twice on purpose. An artifact thumbnail hydrates asynchronously and
  // grows the transcript underneath the first jump, which would otherwise leave
  // the newest turn just short of the bottom -- the same amount wrong, quietly.
  function scrollTranscriptToNewest() {
    const jump = () => {
      const root = surface();
      const transcript = root && transcriptScroller(root);
      if (transcript) transcript.scrollTop = transcript.scrollHeight;
    };
    jump();
    // Guarded: this module is also loaded by a Node contract test that stubs a
    // DOM but has no rAF, and an unguarded call took that test down with a
    // ReferenceError.
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(jump);
  }

  function captureRenderState(root) {
    const active = document.activeElement;
    const steer = root.querySelector('#tc-code-steer');
    const transcript = transcriptScroller(root);
    return {
      activeId: active && root.contains(active) ? active.id : '',
      steerValue: steer ? steer.value : '',
      steerStart: steer && typeof steer.selectionStart === 'number' ? steer.selectionStart : null,
      steerEnd: steer && typeof steer.selectionEnd === 'number' ? steer.selectionEnd : null,
      transcriptScroll: transcript ? transcript.scrollTop : 0,
    };
  }

  function restoreRenderState(root, saved) {
    const steer = root.querySelector('#tc-code-steer');
    const transcript = transcriptScroller(root);
    if (steer) steer.value = saved.steerValue;
    if (transcript) transcript.scrollTop = saved.transcriptScroll;
    const active = saved.activeId && root.querySelector(`#${saved.activeId}`);
    if (active) {
      active.focus();
      if (typeof active.setSelectionRange === 'function' && saved.steerStart !== null) active.setSelectionRange(saved.steerStart, saved.steerEnd);
    }
  }

  function updateRunStatus() {
    if (!adapterActive) return;
    const badge = surface()?.querySelector('.tc-mode-status'); if (!badge) return;
    const labels = { ready: 'Ready', working: 'Working', stopping: 'Stopping', approval: 'Approval required', completed: 'Completed', noop: 'No changes made', stopped: 'Stopped', disconnected: 'Disconnected', failed: 'Needs attention' };
    badge.className = `tc-mode-status is-${state.runStatus}`;
    badge.textContent = labels[state.runStatus] || 'Ready';
  }

  // While a run is writing, re-read whatever page is being previewed so it
  // updates in front of you. Throttled, and only for a rendered page that is
  // already open -- this never opens a preview on its own.
  let _previewRefreshAt = 0;
  function refreshOpenPagePreview() {
    const open = state.filePreview;
    if (!open || state.filePreviewRendered === false) return;
    if (!/\.x?html?$/i.test(String(open.path || ''))) return;
    const now = Date.now();
    if (now - _previewRefreshAt < 1500) return;
    _previewRefreshAt = now;
    void loadFile(open.path).catch(() => {});
  }

  function pushLiveEvent(event) {
    annotateTerminalEvent(event, {
      get name() { return state.terminalTool; },
      set name(value) { state.terminalTool = value; },
    });
    if (state.running) refreshOpenPagePreview();
    const previous = state.liveEvents[state.liveEvents.length - 1];
    if (event.kind === 'say' && event.delta && previous && previous.kind === 'say' && previous.delta) {
      previous.text = `${previous.text || ''}${event.text || ''}`;
      return true;
    }
    state.liveEvents.push(event);
    while (state.liveEvents.length > MAX_LIVE_EVENTS) state.liveEvents.shift();
    return false;
  }

  function trimLiveEventDom(list) {
    const finalEvent = finalReplyEvent(state.liveEvents);
    const narrativeCount = progressEvents(state.liveEvents, finalEvent).filter(event => !isTechnicalEvent(event)).length;
    while (list.children.length > narrativeCount || list.children.length > MAX_LIVE_EVENTS) list.firstElementChild.remove();
  }

  function appendLiveEvent(event, replaceLast) {
    const list = surface()?.querySelector('#tc-code-live-events'); if (!list) { render(); return; }
    const transcript = transcriptScroller(surface());
    const nearBottom = !transcript || transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 80;
    if (state.liveEvents.length === MAX_LIVE_EVENTS) {
      render();
      return;
    }
    if (eventType(event) === 'final') {
      render();
      return;
    }
    // Every event — narrative AND technical (tool/terminal) — streams inline in
    // arrival order into the single live feed, so the run reads action-by-action
    // in the chat instead of hiding tool work behind a collapsed block.
    const progressCount = state.liveEvents.filter(item => ['insight', 'planning', 'say'].includes(eventType(item))).length;
    if (progressCount > MAX_VISIBLE_PROGRESS_EVENTS) {
      render();
      const nextTranscript = transcriptScroller(surface());
      if (nearBottom && nextTranscript) nextTranscript.scrollTop = nextTranscript.scrollHeight;
      return;
    }
    if (replaceLast && list.lastElementChild) list.lastElementChild.outerHTML = eventHtml(state.liveEvents[state.liveEvents.length - 1], false);
    else list.insertAdjacentHTML('beforeend', eventHtml(event, false));
    trimLiveEventDom(list);
    if (nearBottom && transcript) transcript.scrollTop = transcript.scrollHeight;
  }

  function closeSource() {
    const source = state.source;
    state.source = null;
    if (source) source.close();
  }

  // Parallel runs (Codex-style): switching away from a RUNNING conversation
  // parks it — the backend keeps working, and opening that conversation again
  // reattaches via its run_id + cursor (same machinery as reload-resume).
  function parkActiveRun() {
    if (!state.running || !state.activeId || !state.runId) return;
    state.parkedRuns = state.parkedRuns || {};
    state.parkedRuns[state.activeId] = { runId: state.runId, startedAt: state.runStartedAt || Date.now(), cursor: state.eventCursor || 0 };
    closeSource();
    state.running = false;
    host().setBusy && host().setBusy(false);
  }

  function canSwitchContext() {
    if (!state.approvalBusy && !state.steeringBusy && !state.finishing) {
      // A live run no longer blocks switching — it parks and keeps running.
      if (state.running) {
        if (!state.runId) {
          recordError(null, 'Wait for this Code task to start before switching.');
          return false;
        }
        parkActiveRun();
      }
      return true;
    }
    recordError(null, 'Finish the pending Code approval or steering update before switching.');
    return false;
  }

  function clearContextState() {
    closeSource();
    // Cleared BEFORE finishBusy, which repaints the project chip: leaving the
    // outgoing conversation's id in place made that repaint describe a task
    // that is already gone. At this point nothing is bound, and the chip has to
    // be allowed to say so.
    state.activeId = '';
    state.conversation = null;
    finishBusy();
    state.liveEvents = [];
    // The echoed message belongs to the conversation it was typed into. The
    // render only suppresses it once the SAME text appears in `turns`, so
    // carrying it across a switch would print it into somebody else's
    // transcript, where nothing would ever match it and it would simply stay.
    state.pendingUserText = '';
    state.changes = [];
    state.tree = [];
    state.treeLoaded = false;
    state.treePath = '';
    state.artifacts = [];
    state.artifactDocs = {};
    state.previewBase = null;
    state.artifactOpen = {};
    state.filePreview = null;
    state.pendingApproval = null;
    state.pendingRequest = null;
    state.approvalBusy = false;
    state.steeringBusy = false;
    state.terminalTool = '';
    state.runProof = null;
    state.runId = '';
    state.eventCursor = 0;
    state.retryRequest = null;
    state.runStatus = 'ready';
  }

  function replacePendingApproval(data, request) {
    const retry = { ...request };
    delete retry.approval_id;
    state.pendingApproval = data.approval;
    state.pendingRequest = retry;
    state.runStatus = 'approval';
    pushLiveEvent({ type: 'approval', text: data.error || 'Fresh approval is required before Thomas can continue.' });
  }

  function adoptStartedConversation(conversationId, projectRoot, runId) {
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

  async function acceptStartedRun(data) {
    adoptStartedConversation(data.conversation_id, data.project_root, data.run_id);
    lifecycle().registerRunProof(state, data.conversation_id, data.run_id);
    state.retryRequest = null;
    state.pendingApproval = null;
    state.pendingRequest = null;
    if (data.run_state === 'completed' || data.run_state === 'persistence_failed') {
      // The same predicate the streaming `done` frame uses -- see
      // `terminalRunStatus`. This line used to spell the decision a second time
      // and read `data.outcome`, which is why a replayed conversational answer
      // landed on the badge as the raw word 'conversation'.
      state.runStatus = terminalRunStatus(data);
      const epoch = state.contextEpoch;
      const runId = state.runId;
      const proof = state.runProof ? { ...state.runProof } : null;
      const results = await Promise.allSettled([loadConversation(data.conversation_id, { internal: true, epoch, deferRender: true }), refresh({ throwOnError: true })]);
      const loaded = results[0].status === 'fulfilled' && results[0].value === true;
      const durable = data.persistence_confirmed === true && loaded && state.contextEpoch === epoch && state.runId === runId && lifecycle().runIsDurable(state.conversation, proof);
      if (durable) {
        state.liveEvents = [];
        state.artifacts = [];
        state.runProof = null;
      } else {
        state.runStatus = 'failed';
        pushLiveEvent({ type: 'error', text: 'Thomas finished, but the durable Code reply could not be confirmed. Live evidence was preserved.' });
      }
      results.filter(result => result.status === 'rejected').forEach(result => pushLiveEvent({ type: 'error', text: errorText(result.reason, 'The Code result could not be refreshed.') }));
      finishBusy(); render(); return durable;
    }
    openStream();
    await refresh();
    return true;
  }

  // A blank Code surface used to be one line of encouragement above 700px of
  // empty space -- measured on a 1920x1080 screen, the hero sat at the top and
  // nothing else occupied the view down to the composer. It told you to
  // describe an outcome without showing what a good one looks like.
  //
  // These fill the composer rather than sending. A starter is a suggestion, and
  // a click that silently spends a model call on a prompt nobody read is a
  // worse surprise than one extra keystroke.
  const CODE_STARTERS = [
    { icon: 'ph-play-circle', title: 'A small game', text: 'Build a playable Minesweeper in index.html. A 9x9 grid with 10 mines, left click reveals, right click flags, and a mine counter. Plain HTML/CSS/JS.' },
    { icon: 'ph-chart-bar', title: 'A chart from data', text: 'Build report.html that reads sales.csv from the same folder and draws a bar chart of revenue per region on a canvas, with the grand total shown as text.' },
    { icon: 'ph-app-window', title: 'A little tool', text: 'Build a habit tracker in index.html: a seven day grid, click a day to toggle it done, a current streak count, and it remembers what I ticked after a reload.' },
    { icon: 'ph-wrench', title: 'Work on my code', text: 'Look at the project I have selected, tell me what it does, and suggest the three changes that would improve it most.' },
  ];

  function emptyStateHtml() {
    const cards = CODE_STARTERS.map(s => `<button class="tc-code-starter" type="button" data-code-starter="${esc(s.text)}">
      <i class="ph ${s.icon}" aria-hidden="true"></i>
      <span class="tc-code-starter-title">${esc(s.title)}</span>
      <span class="tc-code-starter-text">${esc(s.text.length > 96 ? `${s.text.slice(0, 96).trim()}…` : s.text)}</span>
    </button>`).join('');
    return `<div class="tc-code-empty">
      <span class="tc-code-avatar" aria-hidden="true"><i class="ph ph-robot"></i></span>
      <strong>What should we make?</strong>
      <span class="tc-code-empty-intro">Describe the outcome in the composer below. Keep using this same conversation for changes, tests, and review.</span>
      <div class="tc-code-starters">${cards}</div>
    </div>`;
  }


  function render() {
    if (!adapterActive) return;
    const root = surface(); if (!root) return;
    const savedRenderState = captureRenderState(root);
    const statusLabels = { ready: 'Ready', working: 'Working', stopping: 'Stopping', approval: 'Approval required', completed: 'Completed', noop: 'No changes made', stopped: 'Stopped', disconnected: 'Disconnected', failed: 'Needs attention' };
    const turns = state.conversation && Array.isArray(state.conversation.turns) ? state.conversation.turns : [];
    const liveFinalEvent = finalReplyEvent(state.liveEvents);
    const liveActivityEvents = progressEvents(state.liveEvents, liveFinalEvent);
    // Codex-style: stream EVERY action inline in arrival order as it happens —
    // tool runs and terminal commands ("Used Read", "Ran terminal command") land
    // right next to the narrative updates instead of being hidden in a collapsed
    // "Show details" block. (Owner: "he doesn't output stuff in the chat, he
    // outputs it in the activity thing on the side.")
    const liveNarrative = liveActivityEvents.map(event => eventHtml(event, false)).join('');
    const liveErrors = state.liveEvents.filter(event => eventType(event) === 'error');
    const liveReply = liveFinalEvent
      ? `<div class="tc-code-reply">${replyHtml(eventLabel(liveFinalEvent))}</div>`
      : liveErrors.length ? `<div class="tc-code-reply is-error">${esc(failureSummary({ ok: false }, liveErrors))}</div>` : '';
    const liveTechnical = '';
    // Hoisted so the empty state below is decided by the SAME condition that
    // decides whether a live turn is drawn. Two expressions meaning "a run is on
    // screen" is how they drift apart and both render at once -- which is
    // precisely the bug this fixes.
    const hasLiveTurn = Boolean(state.running || state.liveEvents.length);
    // The page you SEND from never showed you your own message. `turns` comes
    // from `state.conversation`, which is only refreshed from the server, so
    // between pressing Enter and the run finishing the words you just typed were
    // nowhere on screen. Measured on a live run at 1920:
    // `.tc-code-turn.is-user` count was 0 while the live turn was already
    // streaming, and the same conversation opened in a second tab showed the
    // message fine -- so it was never missing data, only a missing render.
    //
    // Suppressed as soon as the server's copy arrives, decided at RENDER time
    // rather than cleared on a lifecycle event. A clear that fires at the wrong
    // moment leaves either no bubble or two identical ones; this cannot do
    // either, because the pending copy is simply not drawn once `turns` has it.
    // Compared on trimmed text, which is what the server round-trips.
    const pendingUser = String(state.pendingUserText || '').trim();
    const serverHasPending = Boolean(
      pendingUser
      && turns.some(turn => turn && turn.role === 'user' && String(turn.text || '').trim() === pendingUser),
    );
    const pendingUserTurn = pendingUser && !serverHasPending
      ? turnHtml({ role: 'user', text: pendingUser })
      : '';
    const liveTurn = hasLiveTurn
      // `is-live` only while the run actually is. The class drives
      // `.tc-code-turn.is-live … small::after { content: ' · working' }`, and it
      // was set for as long as a live turn existed at all -- which outlives the
      // run. After Stop the header read "Thomas · Code · working" directly above
      // its own note saying "Stopped — you interrupted this run." Measured:
      // status "Stopped", turn still carrying is-live, suffix still " · working".
      //
      // `state.running` is the same condition the steer form already uses to hide
      // itself on stop, so the two now agree instead of disagreeing.
      ? `<article class="tc-code-turn is-agent${state.running ? ' is-live' : ''}" data-code-live-turn><div class="tc-code-message-head"><span class="tc-code-avatar" aria-hidden="true"><i class="ph ph-robot"></i></span><strong>Thomas</strong><small>Code</small></div><div class="tc-code-turn-body"><div id="tc-code-live-events" aria-live="polite">${liveNarrative}</div><div id="tc-code-live-technical">${liveTechnical}</div>${liveReply}</div></article>`
      : '<div id="tc-code-live-events" hidden></div><div id="tc-code-live-technical" hidden></div>';
    const visibleChanges = state.changes.filter(change => !isInternalResultPath(change.file));
    const changeRows = visibleChanges.map(change => `<article class="tc-code-change"><header><strong>${esc(change.file)}</strong><span><button data-code-keep="${esc(change.file)}">Keep</button><button data-code-revert="${esc(change.file)}">Revert</button></span></header><details><summary>View ${change.untracked ? 'new file' : 'diff'}</summary><pre>${esc(change.diff || (change.untracked ? 'New file' : 'No textual diff'))}</pre></details></article>`).join('');
    const treeRows = state.tree.slice(0, 120).map(row => row.kind === 'directory' ? `<li class="is-dir"><button data-code-tree-dir="${esc(row.path)}"><i class="ph ph-caret-right"></i>${esc(row.name)}</button></li>` : row.kind === 'file' ? `<li><button data-code-tree-file="${esc(row.path)}"><i class="ph ph-file-code"></i><span>${esc(row.name || row.path || '')}</span></button></li>` : `<li><i class="ph ph-file"></i>${esc(row.name || row.path || '')}</li>`).join('');
    const artifacts = [];
    const artifactKeys = new Set();
    turns.flatMap(turn => turn.artifacts || []).concat(state.artifacts).filter(artifact => !isInternalResultPath(artifact.file)).forEach(artifact => {
      const key = `${artifact.file || ''}\u0000${artifact.kind || ''}`;
      if (!artifactKeys.has(key)) { artifactKeys.add(key); artifacts.push(artifact); }
    });
    const artifactRows = artifacts.map(codeResults().artifactHtml).join('');
    // The drawer's "Outputs" section holds two different kinds of thing: the
    // deliverable (preview + artifact rows) and the changed files you can Keep
    // or Revert. The deliverable is almost always ALSO a changed file, so its
    // name renders twice under one heading. Measured on the three-file kanban
    // run, reading down the single "Outputs" column:
    //     index.html   (artifact, with preview)
    //     app.js       (change row, Keep/Revert)
    //     index.html   (change row, Keep/Revert)   <- the same name again
    //     styles.css   (change row, Keep/Revert)
    // Scanning it, the repeat reads as a rendering fault rather than as "the
    // thing you made" and "a file you may revert".
    //
    // Labelled rather than de-duplicated: dropping the second row would take
    // away the only Revert control for the deliverable, which is the one file
    // you are most likely to want to undo.
    //
    // Only when something precedes it -- with no preview and no artifacts there
    // is a single group, and a second heading straight under "Outputs" would
    // separate nothing. `.tc-code-section-title` has symmetric 8px margins, so
    // it sits correctly mid-section with no CSS change.
    // Defined AFTER `preview` further down, not here: `preview` is a `const`
    // declared later in this function, so reading it at this point is a
    // temporal-dead-zone ReferenceError that takes out the whole of Code mode.
    const hasResults = Boolean(state.pendingApproval || visibleChanges.length || artifacts.length || state.filePreview);
    // Watch it build. A generated page is far more useful rendered than as
    // source, and during a run this refreshes, so you see the thing take shape
    // instead of reading a diff and hoping. Sandboxed WITHOUT allow-same-origin:
    // srcdoc inherits this page's origin, and a generated app must never be
    // able to reach into Thomas. Scripts run, so games and animations work;
    // localStorage does not, which a small number of generated apps rely on.
    const previewIsPage = state.filePreview && /\.x?html?$/i.test(String(state.filePreview.path || ''));
    const previewBody = (previewIsPage && state.filePreviewRendered !== false)
      // A miniature of the page, not a crop of its top-left corner.
      //
      // This rendered the document at 1:1 into the drawer's ~247px column, so a
      // layout built for ~1200px arrived as a keyhole: "Sort by amount" cut to
      // "Sort by", the table header reading "DATE DESCRIPTION AM…", about a
      // fifth of the page visible and every edge sliced mid-word. It reads as a
      // broken render rather than a preview.
      //
      // Exactly the mistake the artifact thumbnail had and had already fixed --
      // a different element, so the fix never reached here. Same fixed box and
      // same fixed scale, deliberately not percentages: the drawer is resizable
      // (280-520px) and a proportional preview would drift with it instead of
      // being the same picture every time. 1280x1600 at 0.19375 lands on
      // 248x310, which is the thumbnail's scale over twice its height, because
      // this one was opened on purpose.
      ? `<div class="tc-code-file-shot"><iframe title="Preview of ${esc(state.filePreview.path)}" sandbox="allow-scripts" srcdoc="${esc(String(state.filePreview.content || ''))}" tabindex="-1" scrolling="no"></iframe></div>`
      : (state.filePreview ? `<pre>${esc(state.filePreview.content)}</pre>` : '');
    const previewToggle = previewIsPage
      ? `<button data-code-preview-toggle style="margin-right:6px;">${state.filePreviewRendered === false ? 'Show page' : 'Show code'}</button>`
      : '';
    const preview = state.filePreview ? `<section class="tc-code-file-preview"><header><strong>${esc(state.filePreview.path)}</strong>${previewToggle}<button data-code-file-close aria-label="Close file preview"><i class="ph ph-x"></i></button></header>${previewBody}</section>` : '';
    const approval = state.pendingApproval ? `<section class="tc-code-approval" role="alert" data-ui-id="code.approval" data-ui-label="Approval required" data-ui-policy="protected"><strong>Approval required</strong><p>${esc(state.pendingApproval.summary)}</p><div><button data-code-approve ${state.approvalBusy ? 'disabled' : ''}>${state.approvalBusy ? 'Approving...' : 'Approve once'}</button><button data-code-approval-cancel ${state.approvalBusy ? 'disabled' : ''}>Cancel</button></div></section>` : '';
    // Separates the two groups the "Outputs" heading covers -- see the note
    // beside `artifactRows` above for the measurement. Declared here rather than
    // there because `preview` is a `const` on the line above this one.
    const changesTitle = (preview || artifactRows) && changeRows
      ? '<div class="tc-code-section-title">Changed files</div>' : '';
    // The history question. Same shape as the approval prompt above, because it
    // is the same kind of moment: Thomas needs an answer before it can act, and
    // the answer belongs on screen rather than in a log file.
    const historyAsk = state.pendingHistoryChoice ? `<section class="tc-code-approval" role="alert"><strong>${esc(state.pendingHistoryChoice.projectName || 'This folder')} has no version history</strong><p>${esc(state.pendingHistoryChoice.message)}</p><div><button data-code-history-setup ${state.historyChoiceBusy ? 'disabled' : ''}>${state.historyChoiceBusy ? 'Working...' : 'Set up history'}</button><button data-code-history-without ${state.historyChoiceBusy ? 'disabled' : ''}>Work without undo</button><button data-code-history-cancel ${state.historyChoiceBusy ? 'disabled' : ''}>Cancel</button></div></section>` : '';
    const projectLabel = state.projectRoot ? codeProjects().projectDisplayLabel() : 'Choose a project';
    // An empty file list has three different causes and used to name only one:
    // it always read "Choose a project beside Tools to browse its files."
    //
    // Measured on a new task: for 45 seconds -- the whole run -- the drawer
    // header said "Code task 2026-07-30 1018" while the list directly beneath it
    // told you to choose a project. The header has always used `state.projectRoot`
    // for exactly this decision; the list simply did not ask.
    //
    // `treeLoaded` separates the other two, which no existing field could: a
    // fetch that has not returned yet is not the same as a folder with nothing
    // in it, and saying "no files" while still loading would be the same kind of
    // guess in a new coat.
    const filesEmptyMessage = !state.projectRoot
      ? 'Choose a project beside Tools to browse its files.'
      : (state.treeLoaded ? 'This folder has no files yet.' : 'Loading files…');
    // `is-viewer-open` lets the layout make room for the viewer.
    //
    // The artifact card promises "Click to open it beside the chat" and the
    // viewer's own stylesheet comment says "beside the conversation", but it is
    // `position: absolute`, so it never moved anything: measured at 1920 wide,
    // the transcript stayed 768px at x=716 while the viewer covered x=1160
    // onward -- 324px of the conversation underneath it, clipping 300px off
    // every line of Thomas's reply mid-word.
    //
    // Not applied when the viewer is full-bleed: it covers the surface
    // deliberately then, and reserving room behind it would only squeeze a
    // layout nobody can see.
    const viewerOpen = Boolean(state.viewer && state.viewer.file);
    const viewerFull = Boolean(state.viewer && state.viewer.full);
    root.innerHTML = `<div class="tc-code-panel${state.drawerOpen ? ' is-drawer-open' : ''}${viewerOpen && !viewerFull ? ' is-viewer-open' : ''}" style="--tc-code-drawer-width:${clampDrawerWidth(state.drawerWidth)}px">
      <header class="tc-code-context" data-ui-id="code.context" data-ui-label="Code activity bar" data-ui-policy="move"><button data-code-results-jump type="button" aria-expanded="${state.drawerOpen ? 'true' : 'false'}"><i class="ph ph-sidebar-simple"></i> Activity <small>${statusLabels[state.runStatus] || 'Ready'}</small>${hasResults ? '<span class="tc-code-activity-count" aria-hidden="true"></span>' : ''}</button></header>
      <div class="tc-code-layout">
        <section class="tc-code-transcript" aria-label="Code conversation" data-ui-id="code.transcript" data-ui-label="Code conversation" data-ui-policy="move resize" data-ui-constraints="minWidth=320;minHeight=200">${historyAsk}<div id="tc-code-turns">${turns.map(turnHtml).join('') || (hasLiveTurn || pendingUserTurn ? '' : emptyStateHtml())}</div>${pendingUserTurn}${liveTurn}</section>
        <aside class="tc-code-actions" aria-label="Code activity" aria-hidden="${state.drawerOpen ? 'false' : 'true'}"${state.drawerOpen ? '' : ' inert'} data-ui-id="code.activity" data-ui-label="Code activity drawer" data-ui-policy="move resize" data-ui-constraints="minWidth=280;minHeight=240;maxWidth=520"><section class="tc-code-rail-section" data-ui-id="code.outputs" data-ui-label="Outputs" data-ui-policy="move resize" data-ui-constraints="minWidth=240;minHeight=120"><div class="tc-code-section-title">Outputs</div>${approval}${preview}${artifactRows}${changesTitle}${changeRows || (!preview && !artifactRows ? '<p class="tc-code-rail-empty">Previews, changed files, and proof will appear here without interrupting the conversation.</p>' : '')}${changeRows && !state.running ? `<button id="tc-code-checkpoint" class="tc-code-checkpoint" data-ui-id="code.action.checkpoint" data-ui-label="Checkpoint changes" data-ui-policy="protected" title="Commit these changes on a thomas-code/ branch">Checkpoint — commit these changes</button>` : ''}</section><section class="tc-code-rail-section tc-code-tree" data-ui-id="code.files" data-ui-label="Project files" data-ui-policy="move resize" data-ui-constraints="minWidth=240;minHeight=120"><div class="tc-code-tree-head"><div class="tc-code-section-title">Files · ${esc(state.treePath || '/')}</div>${state.treePath ? '<button id="tc-code-tree-up">Up</button>' : ''}</div><ul>${treeRows || `<li class="tc-code-muted">${esc(filesEmptyMessage)}</li>`}</ul></section><form id="tc-code-steer-form" class="tc-code-steer" ${state.running ? '' : 'hidden'} data-ui-id="code.steer" data-ui-label="Steer Thomas" data-ui-policy="move resize" data-ui-constraints="minWidth=240;minHeight=80"><label for="tc-code-steer">Steer Thomas</label><input id="tc-code-steer" name="message" required placeholder="Change direction…" ${state.steeringBusy ? 'disabled' : ''}><button ${state.steeringBusy ? 'disabled' : ''}>${state.steeringBusy ? 'Confirming…' : 'Apply'}</button><button type="button" id="tc-code-stop" data-ui-id="code.action.stop" data-ui-label="Stop this run" data-ui-policy="protected" title="Stop this run" ${state.steeringBusy ? 'disabled' : ''}>Stop</button></form></aside>
      </div>${codeResults().viewerHtml()}</div>`;
    const activityDrawer = root.querySelector('.tc-code-actions');
    codeResults().bindViewer(root, render);
    activityDrawer?.insertAdjacentHTML('afterbegin', `<div class="tc-code-drawer-resize" role="separator" tabindex="0" aria-orientation="vertical" aria-label="Resize activity drawer" aria-valuemin="280" aria-valuemax="520" aria-valuenow="${state.drawerWidth}"></div><header class="tc-code-drawer-head"><div><strong>Activity</strong><small>${esc(projectLabel)}</small></div><button data-code-drawer-close type="button" aria-label="Close activity"><i class="ph ph-x"></i></button></header>`);
    root.querySelector('[data-code-results-jump]')?.addEventListener('click', () => { state.drawerOpen = !state.drawerOpen; render(); });
    root.querySelector('[data-code-drawer-close]')?.addEventListener('click', () => { state.drawerOpen = false; render(); });
    const resizeHandle = root.querySelector('.tc-code-drawer-resize');
    const panel = root.querySelector('.tc-code-panel');
    const setDrawerWidth = width => {
      state.drawerWidth = clampDrawerWidth(width);
      panel?.style.setProperty('--tc-code-drawer-width', `${state.drawerWidth}px`);
      resizeHandle?.setAttribute('aria-valuenow', String(state.drawerWidth));
    };
    const saveDrawerWidth = () => {
      try { localStorage.setItem('thomas_code_drawer_width', String(state.drawerWidth)); }
      catch (error) { recordPreferenceWarning(error, 'The activity drawer width could not be saved.'); }
    };
    resizeHandle?.addEventListener('pointerdown', event => {
      event.preventDefault();
      resizeHandle.setPointerCapture?.(event.pointerId);
      const move = moveEvent => { setDrawerWidth(window.innerWidth - moveEvent.clientX); };
      const done = () => {
        resizeHandle.removeEventListener('pointermove', move);
        resizeHandle.removeEventListener('pointerup', done);
        resizeHandle.removeEventListener('pointercancel', done);
        saveDrawerWidth();
      };
      resizeHandle.addEventListener('pointermove', move);
      resizeHandle.addEventListener('pointerup', done);
      resizeHandle.addEventListener('pointercancel', done);
    });
    resizeHandle?.addEventListener('keydown', event => {
      const widths = { ArrowLeft: state.drawerWidth + 16, ArrowRight: state.drawerWidth - 16, Home: 280, End: 520, PageUp: state.drawerWidth + 48, PageDown: state.drawerWidth - 48 };
      if (!(event.key in widths)) return;
      event.preventDefault();
      setDrawerWidth(widths[event.key]);
      saveDrawerWidth();
    });
    root.querySelector('#tc-code-tree-up')?.addEventListener('click', () => { const parts = state.treePath.split('/'); parts.pop(); void safely(() => loadTree(parts.join('/')), 'Could not open that folder.'); });
    root.querySelectorAll('[data-code-tree-dir]').forEach(button => button.addEventListener('click', () => { void safely(() => loadTree(button.dataset.codeTreeDir), 'Could not open that folder.'); }));
    root.querySelectorAll('[data-code-tree-file]').forEach(button => button.addEventListener('click', () => { void safely(() => loadFile(button.dataset.codeTreeFile), 'Could not preview that file.'); }));
    root.querySelector('[data-code-file-close]')?.addEventListener('click', () => { state.filePreview = null; render(); });
    root.querySelector('[data-code-preview-toggle]')?.addEventListener('click', () => { state.filePreviewRendered = state.filePreviewRendered === false; render(); });
    root.querySelectorAll('[data-code-open-artifact]').forEach(button => button.addEventListener('click', () => {
      // Opens IN THE CONVERSATION. Sending the result to a side panel is still
      // telling someone where to go and look; Chat puts a deliverable in the
      // thread and Code is meant to be Chat that builds rather than dispatches.
      const file = button.dataset.codeOpenArtifact;
      const slot = button.dataset.codeArtifactSlot || file;
      state.artifactOpen = state.artifactOpen || {};
      state.artifactOpen[slot] = true;
      // Opens BESIDE the conversation rather than inside it. The card stays a
      // snapshot you can read at a glance; the real thing gets the height of
      // the window, and from there it can fill Thomas or leave for its own tab.
      codeResults().openViewer(file);
      render();
      // Fetch the previewable copy after the panel is up, then redraw so the
      // frame swaps from the plain artifact URL to the asset-inlined document.
      void safely(async () => { await codeResults().ensureArtifactDoc(file); render(); }, 'That result could not be opened.');
    }));
    root.querySelectorAll('[data-code-save-artifact]').forEach(button => button.addEventListener('click', () => {
      // Saved from the file Thomas actually wrote, read through the same
      // validated endpoint. Not the inlined preview copy, which carries
      // dependencies folded in for display only.
      const file = button.dataset.codeSaveArtifact;
      void safely(async () => {
        const token = lifecycle().contextToken(state);
        if (!token.id) return false;
        const content = await codeResults().readProjectFile(token.id, file);
        if (content === null) throw new Error('could not read ' + file);
        const url = URL.createObjectURL(new Blob([content], { type: 'application/octet-stream' }));
        const a = document.createElement('a');
        a.href = url; a.download = file.split('/').pop();
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
        return true;
      }, 'That result could not be downloaded.');
    }));
    root.querySelector('[data-code-approve]')?.addEventListener('click', () => { void safely(approvePending, 'Approval could not be completed.'); });
    root.querySelector('[data-code-approval-cancel]')?.addEventListener('click', () => { state.pendingApproval = null; state.pendingRequest = null; state.runStatus = 'stopped'; pushLiveEvent({ type: 'stopped', text: 'Approval cancelled. No Code action was run.' }); render(); });
    const answerHistory = (choice) => {
      const ask = state.pendingHistoryChoice;
      if (!ask || state.historyChoiceBusy) return;
      state.historyChoiceBusy = true;
      render();
      void safely(async () => {
        try {
          const ok = await newConversation(ask.projectRoot, ask.projectLabel, { historyChoice: choice });
          if (ok) pushLiveEvent({ type: 'planning', text: choice === 'setup' ? `Version history set up in ${ask.projectName}. Thomas can undo its edits here.` : `Opened ${ask.projectName} without undo. Thomas cannot revert its own edits in this folder.` });
        } finally {
          state.historyChoiceBusy = false;
          render();
        }
      }, 'That folder could not be opened.');
    };
    root.querySelector('[data-code-history-setup]')?.addEventListener('click', () => answerHistory('setup'));
    root.querySelector('[data-code-history-without]')?.addEventListener('click', () => answerHistory('without'));
    root.querySelector('[data-code-history-cancel]')?.addEventListener('click', () => { state.pendingHistoryChoice = null; state.historyChoiceBusy = false; render(); });
    // A starter loads the composer and hands the cursor over. It deliberately
    // does NOT send: the text is a suggestion to edit, and a click that quietly
    // spends a model call on a prompt nobody read is the worse surprise.
    root.querySelectorAll('[data-code-starter]').forEach(card => card.addEventListener('click', () => {
      const input = document.getElementById('tc-input');
      if (!input) return;
      input.value = card.dataset.codeStarter || '';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
      try { input.setSelectionRange(input.value.length, input.value.length); } catch (error) { /* not a text input */ }
    }));
    root.querySelector('#tc-code-steer-form')?.addEventListener('submit', event => { event.preventDefault(); void safely(() => steer(new FormData(event.currentTarget).get('message')), 'Could not steer the Code task.'); });
    root.querySelector('#tc-code-stop')?.addEventListener('click', () => { void safely(() => stopRun(), 'Could not stop the Code run.'); });
    root.querySelector('#tc-code-checkpoint')?.addEventListener('click', () => { void safely(() => checkpointChanges(), 'Could not checkpoint the changes.'); });
    root.querySelectorAll('[data-code-copy-reply]').forEach(button => button.addEventListener('click', () => {
      const reply = button.closest('.tc-code-turn')?.querySelector('.tc-code-reply')?.textContent || '';
      void copyReplyText(reply, button);
    }));
    root.querySelectorAll('[data-code-keep]').forEach(button => button.addEventListener('click', () => { void safely(() => changeAction('keep', button.dataset.codeKeep), 'Could not keep that change.'); }));
    root.querySelectorAll('[data-code-revert]').forEach(button => button.addEventListener('click', () => { void safely(() => changeAction('revert', button.dataset.codeRevert), 'Could not revert that change.'); }));
    restoreRenderState(root, savedRenderState);
    codeProjects().updateProjectButton();
  }

  async function refresh(options) {
    try {
      const response = await fetch('/api/evolve/agent/conversations');
      const data = await response.json();
      if (!response.ok || !Array.isArray(data.conversations)) throw new Error(data.error || `Code history could not be refreshed (${response.status})`);
      state.conversations = data.conversations;
      host().renderHistory && host().renderHistory();
      return true;
    } catch (error) {
      host().renderHistory && host().renderHistory();
      if (options && options.throwOnError) throw error;
      recordError(error, 'Code history could not be refreshed.');
      return false;
    }
  }

  function renderHistory(root, query) {
    const term = String(query || '').trim().toLowerCase();
    const rows = state.conversations.filter(row => Number(row.turn_count || 0) > 0 && (!term || String(row.title || '').toLowerCase().includes(term)));
    root.innerHTML = rows.length ? '' : `<div class="tc-mode-empty">${term ? 'No matching code tasks.' : 'No code tasks yet.'}</div>`;
    rows.forEach(row => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'tc-mode-history-row';
      button.innerHTML = `<span>${esc(row.title || 'Untitled task')}</span>`;
      if (row.id === state.activeId) button.classList.add('is-active');
      // Rows stay clickable while a run is live — switching parks the run.
      button.addEventListener('click', () => { void safely(() => loadConversation(row.id), 'Could not open that Code task.'); }); root.appendChild(button);
    });
  }

  async function loadConversation(id, options) {
    const internal = options && options.internal === true;
    if (!internal && !canSwitchContext()) return false;
    const epoch = internal ? Number(options.epoch) : state.contextEpoch + 1;
    if (!internal) state.contextEpoch = epoch;
    if (internal && (id !== state.activeId || epoch !== state.contextEpoch)) return false;
    const response = await fetch(`/api/evolve/agent/conversations/${encodeURIComponent(id)}`);
    const data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || `Code task could not be loaded (${response.status})`);
    if (epoch !== state.contextEpoch) return false;
    if (!internal) clearContextState();
    state.activeId = id;
    state.conversation = data.conversation;
    state.projectRoot = data.conversation.project_root || state.projectRoot;
    // Repaint the chip HERE, not at the render() below. Everything it needs is
    // already known; the render is behind the changes and file-tree fetches,
    // which on a large project take seconds. Sampling the chip 900ms after a
    // click caught 4 of 36 conversations still showing the pre-load repaint
    // from clearContextState -- "A new folder for this task" over a task whose
    // folder was already resolved and sitting in state.
    codeProjects().updateProjectButton();
    const token = lifecycle().contextToken(state);
    await Promise.all([loadChanges({ token, deferRender: true }), loadTree('', { token, deferRender: true })]);
    if (!(options && options.deferRender)) render();
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
      await reattachRunFor(id);
      // A task queued for THIS conversation while it was parked starts now.
      if (!state.running) startNextQueued();
    }
    return true;
  }

  // Reattach to THIS conversation's still-running run (parked earlier or found
  // on the server) — the per-conversation half of reload-resume.
  async function reattachRunFor(cid) {
    if (state.running || state.finishing || state.activeId !== cid) return false;
    const parked = (state.parkedRuns || {})[cid];
    let status;
    try {
      const response = await fetch(`/api/evolve/agent/status?conversation_id=${encodeURIComponent(cid)}`);
      status = await response.json();
    } catch (error) { return false; }
    if (state.activeId !== cid) return false;
    if (!status || status.running !== true || !status.run_id) {
      if (parked) delete state.parkedRuns[cid];
      return false;
    }
    lifecycle().adoptRunIdentity(state, status.run_id);
    if (parked && parked.runId === status.run_id && parked.cursor) state.eventCursor = parked.cursor;
    if (parked) delete state.parkedRuns[cid];
    state.running = true;
    state.runStatus = 'working';
    const startedRaw = (status.session || {}).started_at;
    state.runStartedAt = (parked && parked.startedAt) || (Number(startedRaw) ? Number(startedRaw) * 1000 : Date.parse(String(startedRaw || ''))) || Date.now();
    host().setBusy && host().setBusy(true);
    pushLiveEvent({ type: 'disconnected', text: 'Reattached — this task kept running in the background.' });
    render();
    openStream();
    return true;
  }

  async function newConversation(projectRoot, projectLabel, options) {
    if (!canSwitchContext()) return false;
    const epoch = state.contextEpoch + 1;
    state.contextEpoch = epoch;
    const context = host().getContext ? host().getContext() : {};
    const requestedRoot = String(projectRoot == null ? state.projectRoot : projectRoot).trim();
    const historyChoice = String((options && options.historyChoice) || '').trim();
    const newProjectName = String((options && options.newProjectName) || '').trim();
    const response = await fetch('/api/evolve/agent/conversations/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_root: requestedRoot || undefined, history_choice: historyChoice || undefined, new_project_name: newProjectName || undefined, ...lifecycle().requestSettings(context) }) });
    const data = await response.json();
    // A folder with no version history is a QUESTION, not a failure. Throwing
    // here is what made 117 of this user's 121 projects unopenable: the menu
    // closed, the chip never changed, and the only explanation went to a log.
    if (response.status === 409 && data && data.needs_history_choice) {
      state.pendingHistoryChoice = {
        projectRoot: String(data.project_root || requestedRoot),
        projectName: String(data.project_name || ''),
        message: String(data.error || ''),
        projectLabel: String(projectLabel || ''),
      };
      state.historyChoiceBusy = false;
      render();
      return false;
    }
    if (!response.ok || !data.ok) throw new Error(data.error || 'Could not create Code task.');
    state.pendingHistoryChoice = null;
    if (epoch !== state.contextEpoch) return false;
    clearContextState();
    state.activeId = data.conversation.id;
    state.conversation = data.conversation;
    state.projectRoot = data.conversation.project_root || requestedRoot;
    codeProjects().rememberProjectName(state.projectRoot, projectLabel);
    codeProjects().updateProjectButton();
    try {
      localStorage.setItem('thomas_code_project_root', state.projectRoot);
      localStorage.setItem('thomas_code_project_label', codeProjects().knownProjectName(state.projectRoot));
    } catch (error) { recordError(error, 'Project selection could not be saved for the next session.'); }
    const token = lifecycle().contextToken(state);
    await Promise.all([refresh(), loadTree('', { token, deferRender: true })]);
    render();
    return true;
  }

  async function send(message, context, options) {
    if (state.approvalBusy) throw new Error('A Code approval is in progress. Resolve it before starting another task.');
    // Codex-parity queue: sending while a run is going queues the task and
    // auto-starts it when the current run's result is durable.
    if (state.running || state.finishing) {
      state.queuedSends = state.queuedSends || [];
      // Stamp the conversation at ENQUEUE time — with parallel runs the user
      // may switch away, and a queued task must fire into ITS conversation.
      state.queuedSends.push({ message: String(message || ''), context: context || state.lastContext || {}, cid: state.activeId || '' });
      pushLiveEvent({ type: 'planning', text: `Queued (${state.queuedSends.length} waiting): ${String(message || '').slice(0, 80)}` });
      render();
      return true;
    }
    state.lastContext = context || state.lastContext || {};
    // Echoed by the transcript until the server's copy of this turn arrives.
    // Not set for a steer: `preserveProgress` means the run is continuing and the
    // steering text belongs in the activity feed, not as a new message bubble.
    if (!(options && options.preserveProgress)) state.pendingUserText = String(message || '');
    state.running = true;
    state.runStatus = 'working';
    if (!(options && options.preserveProgress) || !state.runStartedAt) state.runStartedAt = Date.now();
    state.terminalTool = '';
    host().setBusy && host().setBusy(true);
    if (options && options.preserveProgress) pushLiveEvent({ type: 'planning', text: 'Thomas is restarting with your steering update…' });
    else state.liveEvents = [{ type: 'planning', text: 'Thomas is preparing the Code run…' }];
    if (!(options && options.preserveProgress)) state.artifacts = [];
    render();
    let requestBody = null;
    try {
      requestBody = lifecycle().runRequest(state, message, state.lastContext);
      const response = await fetch('/api/evolve/agent/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody) });
      const data = await response.json();
      if (response.status === 409 && data.code === 'approval_required') {
        replacePendingApproval(data, requestBody); finishBusy(); render(); return false;
      }
      if (!response.ok || !data.ok) throw new Error(data.error || `Code request failed (${response.status})`);
      return await acceptStartedRun(data);
    } catch (error) {
      if (requestBody) state.retryRequest = requestBody;
      pushLiveEvent({ type: 'error', text: errorText(error, 'Code request failed.') });
      state.runStatus = 'failed';
      finishBusy();
      render();
      return false;
    }
  }

  function openStream() {
    const previous = state.source; state.source = null; if (previous) previous.close();
    const source = new EventSource(lifecycle().streamUrl(state)); state.source = source;
    source.onmessage = event => {
      if (state.source !== source) return;
      let payload; try { payload = JSON.parse(event.data); } catch (error) { payload = { type: 'text', text: event.data }; }
      if (!lifecycle().acceptEvent(state, payload)) return;
      if (payload.type === 'done' && payload.noop === true && !payload.text) payload.text = 'The process exited cleanly but made no file changes, so this Code task is not complete.';
      const replaced = pushLiveEvent(payload); appendLiveEvent(payload, replaced);
      if (payload.type === 'done') {
        const stopWasPending = state.runStatus === 'stopping';
        state.artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : [];
        // A finished run may have written files the current preview origin was
        // not told about, so stop deriving URLs from it and ask again.
        state.previewBase = null;
        state.artifactDocs = {};
        state.source = null;
        source.close();
        if (stopWasPending) {
          state.runStatus = 'stopped';
          const confirmation = { type: 'stopped', text: `Stop confirmed (process exit ${payload.returncode}).` };
          pushLiveEvent(confirmation);
          appendLiveEvent(confirmation, false);
        } else {
          state.runStatus = terminalRunStatus(payload);
        }
        updateRunStatus();
        if (state.steeringBusy) {
          finishBusy();
          return;
        }
        void safely(finishRun, 'The finished Code task could not be refreshed.');
      }
    };
    source.onerror = () => { void handleStreamError(source); };
  }

  async function handleStreamError(source) {
    if (state.source !== source || !state.running) return false;
    const runId = state.runId;
    const epoch = state.contextEpoch;
    state.source = null;
    source.close();
    let status;
    try {
      const response = await fetch('/api/evolve/agent/status');
      status = await response.json();
      if (!response.ok || !status.ok) throw new Error(status.error || 'Code status check failed.');
    } catch (error) {
      if (state.source || state.runId !== runId || state.contextEpoch !== epoch) return false;
      state.runStatus = 'disconnected';
      pushLiveEvent({ type: 'error', text: `${errorText(error, 'Code status could not be verified.')} Thomas remains locked as running while live updates reconnect.` });
      render();
      openStream();
      return false;
    }
    if (state.source || state.runId !== runId || state.contextEpoch !== epoch || (status.run_id && status.run_id !== runId)) return false;
    if (status.running === true || status.recording === true) {
      state.runStatus = status.running === true ? 'working' : 'stopping';
      const text = status.running === true
        ? 'Live updates were interrupted, but Thomas is still running. Reconnecting without releasing the task.'
        : 'The process stopped and Thomas is still recording the result. Reconnecting until the durable result is ready.';
      pushLiveEvent({ type: 'disconnected', text });
      render();
      openStream();
      return true;
    }
    if (state.steeringBusy) {
      finishBusy();
      return true;
    }
    state.runStatus = 'disconnected';
    pushLiveEvent({ type: 'disconnected', text: 'The stream ended and the backend reports no active or recording Code task.' });
    updateRunStatus();
    await finishRun();
    return true;
  }

  function finishBusy() { state.running = false; host().setBusy && host().setBusy(false); codeProjects().updateProjectButton(); }

  async function finishRun() {
    if (state.finishing) return state.finishing;
    const runId = state.runId;
    state.finishing = (async () => {
      const id = state.activeId;
      const epoch = state.contextEpoch;
      const proof = state.runProof ? { ...state.runProof } : null;
      const results = await Promise.allSettled([id ? loadConversation(id, { internal: true, epoch, deferRender: true }) : Promise.resolve(false), refresh({ throwOnError: true })]);
      const sameRun = state.contextEpoch === epoch && state.runId === runId;
      const durable = results[0].status === 'fulfilled' && results[0].value === true && sameRun && lifecycle().runIsDurable(state.conversation, proof);
      if (durable) {
        state.liveEvents = [];
        state.artifacts = [];
        state.runProof = null;
        // Put the thing Thomas just made in front of the person who asked for
        // it. Finishing a build and leaving the result to be discovered is how
        // "where is it" and "what's the full directory name" became the two
        // messages after a successful game build.
        void codeResults().presentNewestResult();
      } else if (sameRun && results[0].status === 'fulfilled' && results[0].value === true) {
        state.runStatus = 'disconnected';
        pushLiveEvent({ type: 'error', text: 'Thomas stopped, but the just-finished Code turn is not yet present in durable history. Live evidence was preserved.' });
      }
      results.filter(result => result.status === 'rejected').forEach(result => pushLiveEvent({ type: 'error', text: errorText(result.reason, 'The Code result could not be refreshed.') }));
    })();
    try { await state.finishing; } finally {
      const sameRun = state.runId === runId;
      state.finishing = null;
      if (sameRun) {
        finishBusy();
        render();
      }
    }
    // Codex-parity task queue: a message sent while a run was going starts
    // automatically the moment this run's result is durable.
    startNextQueued();
  }
  // Codex-parity checkpoint: turn kept changes into a real commit on a
  // thomas-code/ branch; if the project has a remote, the branch is PR-ready.
  async function checkpointChanges() {
    if (state.running || state.finishing) return false;
    const title = String((state.conversation && state.conversation.title) || 'code changes').slice(0, 60);
    const response = await fetch('/api/evolve/agent/checkpoint', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ conversation_id: state.activeId, message: `Thomas Code: ${title}` }) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || 'Checkpoint failed.');
    const where = data.remote ? ` Push it to open a PR on ${data.remote}.` : '';
    pushLiveEvent({ type: 'insight', text: `Checkpointed ${data.files.length} file(s) as ${data.commit} on ${data.branch}.${where}` });
    render();
    return true;
  }
  function startNextQueued() {
    if (!state.queuedSends || !state.queuedSends.length) return;
    // Drain only tasks queued for the ACTIVE conversation; tasks for a parked
    // conversation wait until the user returns to it (misdelivery guard).
    const index = state.queuedSends.findIndex(entry => !entry.cid || entry.cid === state.activeId);
    if (index < 0) return;
    const queued = state.queuedSends.splice(index, 1)[0];
    pushLiveEvent({ type: 'planning', text: `Starting your queued task: ${queued.message.slice(0, 80)}` });
    render();
    void safely(() => send(queued.message, queued.context), 'The queued Code task failed to start.');
  }
  async function stop() {
    const response = await fetch('/api/evolve/agent/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: state.runId }) });
    const payload = await response.json();
    if (response.status === 202 && payload.code === 'termination_pending') {
      state.runStatus = 'stopping';
      pushLiveEvent({ type: 'stopping', text: 'Stop requested; Thomas is waiting for process termination confirmation.' });
      render();
      return;
    }
    if (!response.ok || payload.termination_confirmed !== true || payload.stopped !== true) throw new Error(payload.error || payload.code || `Stop failed (${response.status})`);
    closeSource();
    state.runStatus = 'stopped';
    pushLiveEvent({ type: 'stopped', text: `Code task stopped (process exit ${payload.returncode}).` });
    await finishRun();
  }
  async function loadChanges(options) {
    const token = (options && options.token) || lifecycle().contextToken(state);
    if (!token.id) return false;
    const response = await fetch(`/api/evolve/agent/changes?cid=${encodeURIComponent(token.id)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Changes could not be loaded (${response.status})`);
    if (!lifecycle().contextMatches(state, token)) return false;
    state.changes = Array.isArray(data.changed) ? data.changed : [];
    if (!(options && options.deferRender)) render();
    return true;
  }
  async function loadTree(path, options) {
    const token = (options && options.token) || lifecycle().contextToken(state);
    if (!token.id) return false;
    const query = path ? `?path=${encodeURIComponent(path)}` : '';
    const response = await fetch(`/api/evolve/agent/conversations/${encodeURIComponent(token.id)}/tree${query}`);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `Project files could not be loaded (${response.status})`);
    if (!lifecycle().contextMatches(state, token)) return false;
    state.tree = Array.isArray(data.entries) ? data.entries : [];
    state.treeLoaded = true;
    state.treePath = String(data.path || '');
    if (!(options && options.deferRender)) render();
    return true;
  }
  async function loadFile(path) {
    const token = lifecycle().contextToken(state);
    if (!token.id) return false;
    const response = await fetch(`/api/evolve/agent/conversations/${encodeURIComponent(token.id)}/file?path=${encodeURIComponent(path)}`);
    const data = await response.json();
    if (!lifecycle().contextMatches(state, token)) return false;
    if (!response.ok || !data.ok) pushLiveEvent({ type: 'error', text: data.error || 'File preview failed.' });
    else {
      if (/\.x?html?$/i.test(String(path))) {
        try { data.content = await codeResults().inlineLocalAssets(token.id, String(data.content || ''), String(path)); }
        catch (e) { /* preview the page as-is rather than not at all */ }
        if (!lifecycle().contextMatches(state, token)) return false;
      }
      state.filePreview = data;
    }
    render();
    return response.ok && data.ok;
  }
  async function changeAction(action, file, approvalId, options) {
    const token = lifecycle().contextToken(state);
    if (!token.id) throw new Error('Open a Code conversation before changing files.');
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
        if (!response.ok || !started.ok) throw new Error(started.error || 'Approved Code task could not start.');
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
  async function waitForRestartReady() {
    // Per-conversation status: with parallel runs, the GLOBAL running flag may
    // be true forever (another project's run) — only THIS conversation matters.
    const statusUrl = state.activeId
      ? `/api/evolve/agent/status?conversation_id=${encodeURIComponent(state.activeId)}`
      : '/api/evolve/agent/status';
    for (let attempt = 0; attempt < 50; attempt += 1) {
      const response = await fetch(statusUrl);
      const status = await response.json().catch(() => null);
      // status.ok describes the LAST RUN's outcome, not endpoint health — a
      // steering-stopped run always reports ok:false (killed, returncode 1),
      // which must not abort the restart. Only an HTTP failure is fatal here.
      if (!response.ok || !status) throw new Error((status && status.error) || 'Steering status check failed.');
      if (status.running === false && status.recording !== true) return true;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error('Thomas is still stopping the previous run. The steering update was not applied; retry it.');
  }
  // Codex-parity interrupt: stop the running turn on demand. Changed files
  // stay in the workspace with Keep/Revert, so stopping is never destructive.
  async function stopRun() {
    if (!state.running || state.steeringBusy) return false;
    state.steeringBusy = true;
    render();
    try {
      const response = await fetch('/api/evolve/agent/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: state.runId }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok && response.status !== 202) throw new Error(data.error || 'Stop failed.');
      await waitForRestartReady();
      closeSource();
      pushLiveEvent({ type: 'stopped', text: 'Stopped — you interrupted this run. Anything already changed is in Outputs with Keep/Revert.' });
      state.runStatus = 'stopped';
      finishBusy();
      startNextQueued();
      return true;
    } finally {
      state.steeringBusy = false;
      render();
    }
  }
  async function steer(message) {
    const text = String(message || '').trim(); if (!text || !state.running || state.steeringBusy) return false;
    state.steeringBusy = true;
    render();
    try {
      const response = await fetch('/api/evolve/agent/steer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text, run_id: state.runId }) });
      const data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || 'Steering failed.');
      pushLiveEvent({ type: 'steering', text: `Steering requested: ${text}` });
      await waitForRestartReady();
      closeSource();
      pushLiveEvent({ type: 'steering', text: 'Previous run stopped. Restarting with the steering update.' });
      finishBusy();
      return await send(`Steering update: ${text}`, state.lastContext, { preserveProgress: true });
    } finally {
      state.steeringBusy = false;
      render();
    }
  }

  if (window.setInterval) window.setInterval(refreshElapsed, 1000);
  try {
    // Migration (v2, 2026-07-19): earlier sessions auto-stored the Thomas source
    // repo as the Code project, so every new conversation silently edited the
    // product tree. The v1 migration cleared it once, but a later run re-saved
    // the repo path (scratch resolved into the repo when the server runs from
    // it). v2 re-clears, and we additionally refuse a stored root that looks
    // like the running server's own source checkout. The server also rejects
    // it as a hard safety net.
    if (localStorage.getItem('thomas_code_project_migrated') !== 'v2') {
      localStorage.removeItem('thomas_code_project_root');
      localStorage.setItem('thomas_code_project_migrated', 'v2');
    }
    const _storedRoot = localStorage.getItem('thomas_code_project_root') || '';
    // Heuristic client guard: a path ending in the Thomas package folder is the
    // source repo — never use it as a scratch Code project.
    state.projectRoot = /[\\/](thomas|thomas-dev)[\\/]?$/i.test(_storedRoot) ? '' : _storedRoot;
    if (!state.projectRoot && _storedRoot) { try { localStorage.removeItem('thomas_code_project_root'); } catch (e) {} }
    // Restore the human name alongside the path, or a returning user is back to
    // reading "exec-25fb7d1499a6" off the chip. Filed against the PATH it names,
    // never held as "the current label": as a single loose value it outlived the
    // project it belonged to and was then printed over every conversation opened
    // afterwards (measured: the chip read one project's name while its own
    // tooltip showed a different project's path).
    codeProjects().rememberProjectName(state.projectRoot, localStorage.getItem('thomas_code_project_label') || '');
  }
  catch (error) { recordError(error, 'The saved Code project could not be loaded.'); }
  try {
    const savedDrawerWidth = Number(localStorage.getItem('thomas_code_drawer_width'));
    if (Number.isFinite(savedDrawerWidth)) state.drawerWidth = clampDrawerWidth(savedDrawerWidth);
  } catch (error) { recordPreferenceWarning(error, 'The saved activity drawer width could not be loaded.'); }

  async function pickProject() {
    if (!canSwitchContext()) return false;
    const response = await fetch('/api/local/projects/pick-folder', { method: 'POST' });
    const contentType = String(response.headers?.get?.('content-type') || '').toLowerCase();
    let data = {};
    let responseText = '';
    if (contentType && !contentType.includes('json') && typeof response.text === 'function') {
      responseText = String(await response.text() || '').trim();
      if (response.ok) throw new Error(`Thomas returned an unreadable folder-picker response (${response.status})`);
    } else {
      try { data = await response.json(); }
      catch (error) {
        if (response.ok) throw new Error(`Thomas returned an unreadable folder-picker response (${response.status})`);
        recordPreferenceWarning(error, 'The folder picker returned a non-JSON error response.');
      }
    }
    if (!response.ok || data.ok === false) throw new Error(data.error || responseText || `Folder picker failed (${response.status})`);
    if (data.cancelled === true) return false;
    if (!data.path) throw new Error('Thomas returned a folder-picker response without a project path.');
    return newConversation(data.path);
  }

  async function leave() {
    adapterActive = false;
    codeProjects().updateProjectButton();
  }

  // Reload-resume (Codex parity): a Code run in progress must survive a page
  // reload — on entering Code mode, reattach to the backend's running run
  // instead of showing a dead surface while the agent keeps working.
  async function adoptOrphanRun() {
    if (state.running || state.finishing) return false;
    let status;
    try {
      const response = await fetch('/api/evolve/agent/status');
      status = await response.json();
    } catch (error) { return false; }
    if (!status || status.running !== true || !status.run_id) return false;
    const session = status.session && typeof status.session === 'object' ? status.session : {};
    const cid = String(session.conversation_id || '');
    if (cid && state.activeId !== cid) {
      try { await loadConversation(cid); } catch (error) {}
    }
    lifecycle().adoptRunIdentity(state, status.run_id);
    state.running = true;
    state.runStatus = 'working';
    if (!state.runStartedAt) state.runStartedAt = Date.parse(String(session.started_at || '')) || Date.now();
    host().setBusy && host().setBusy(true);
    pushLiveEvent({ type: 'disconnected', text: 'Reattached — Thomas kept working through the reload.' });
    render();
    openStream();
    return true;
  }

  modes().registerAdapter('code', {
    enter: async () => { adapterActive = true; codeProjects().updateProjectButton(); render(); void codeProjects().loadProjectNames(); await refresh(); await adoptOrphanRun(); },
    leave,
    refresh,
    renderHistory,
    newConversation: (projectRoot, projectLabel) =>
      safely(() => newConversation(projectRoot, projectLabel), 'Could not create the Code task.'),
    pickProject: () => safely(pickProject, 'Could not choose the project folder.'),
    send: (message, context) => safely(() => send(message, context), 'The Code task failed unexpectedly.'),
    stop: () => { void safely(stop, 'Could not stop the Code task.'); },
    isBusy: () => state.running || Boolean(state.finishing),
  });

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

    void (async () => {
      await modes().setMode('code');
      await safely(() => loadConversation(cid), 'Could not open that Code task.');
    })();
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
