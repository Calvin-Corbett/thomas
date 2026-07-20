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
    conversations: [], activeId: '', conversation: null, liveEvents: [], changes: [], tree: [], treePath: '', artifacts: [], filePreview: null,
    pendingApproval: null, pendingRequest: null, lastContext: {}, running: false, runStartedAt: 0, runStatus: 'ready', source: null,
    finishing: null, approvalBusy: false, steeringBusy: false, projectRoot: '', terminalTool: '', contextEpoch: 0, runProof: null,
    runId: '', eventCursor: 0, retryRequest: null, drawerOpen: false, drawerWidth: 360,
  };
  let adapterActive = false;
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const clampDrawerWidth = value => Math.max(280, Math.min(520, value));
  const modes = () => window.ThomasUnifiedModes;
  const lifecycle = () => window.ThomasCodeLifecycle;
  const host = () => modes().host() || {};
  const surface = () => document.getElementById('tc-mode-surface');

  function errorText(error, fallback) {
    return error instanceof Error && error.message ? error.message : fallback;
  }

  function isInternalResultPath(value) {
    const path = String(value || '').replace(/\\/g, '/').replace(/^\.\/+/, '').toLowerCase();
    return path === '.thomas' || path.startsWith('.thomas/') || path.includes('/.thomas/evolve/agent/');
  }

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

  function terminalRunStatus(payload) {
    if (payload.persistence_confirmed !== true) return 'failed';
    if (payload.noop === true) return 'noop';
    return payload.ok === true ? 'completed' : 'failed';
  }

  function recordError(error, fallback) {
    pushLiveEvent({ type: 'error', text: errorText(error, fallback) });
    // Every user-visible Code failure also lands in the issue ledger report.
    try { fetch('/api/issues', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ surface: 'code-ui', kind: 'action_error', message: errorText(error, fallback).slice(0, 300), context: { runId: state.runId || '' } }) }); } catch (e) {}
    render();
  }

  function recordPreferenceWarning(error, message) {
    console.warn(`[Thomas Code] ${message}`, error);
  }

  async function safely(action, fallback) {
    try { return await action(); }
    catch (error) { recordError(error, fallback); return null; }
  }

  function eventLabel(event) {
    const type = String(event.type || event.fc || 'activity').replace(/_/g, ' ');
    return String(event.text || event.message || event.name || event.tool || event.error || type);
  }

  function eventKind(event) {
    const kind = String(event.kind || event.fc || event.type || 'activity').toLowerCase();
    if (kind === 'reason') return 'Reasoning';
    if (kind === 'insight') return 'Insight';
    if (kind === 'say') return 'Update';
    if (kind === 'final') return 'Thomas';
    if (kind === 'planning') return 'Planning';
    if (kind === 'steering') return 'Steering';
    if (kind === 'error') return 'Error';
    return kind.replace(/_/g, ' ');
  }

  function isTerminalTool(name) {
    return /(?:^|[._-])(shell|bash|powershell|cmd|terminal|command)(?:$|[._-])/i.test(String(name || ''));
  }

  function annotateTerminalEvent(event, tracker) {
    const kind = String(event.kind || event.fc || event.type || 'activity').toLowerCase();
    if (kind === 'tool') {
      tracker.name = isTerminalTool(event.name) ? String(event.name || 'terminal') : '';
      if (tracker.name) { event.terminal = true; event.terminalTool = tracker.name; }
    } else if (kind === 'tool_result' && tracker.name) {
      event.terminal = true; event.terminalTool = tracker.name; tracker.name = '';
    }
    return event;
  }

  function eventType(event) {
    return String(event.kind || event.fc || event.type || 'output').toLowerCase();
  }

  function containsToolProtocol(event) {
    const label = eventLabel(event);
    return /recipient_name|multi_tool_use\.parallel|to=functions\.|<\|assistant\s+to=|\{"tool_uses"\s*:/i.test(label);
  }

  function isTechnicalEvent(event) {
    return event.terminal === true || containsToolProtocol(event) || !NARRATIVE_EVENT_KINDS.has(eventType(event));
  }

  function technicalHeading(event, kind) {
    if (kind === 'reason') return 'Reviewed the approach';
    if (kind === 'error') return 'Technical check failed';
    if (event.terminal === true) {
      if (kind === 'tool') return 'Ran terminal command';
      return event.is_error === true ? 'Terminal check failed' : 'Read terminal result';
    }
    if (kind === 'tool') return `Used ${event.name || 'a project tool'}`;
    if (event.is_error === true) return 'Technical check failed';
    return kind === 'meta' ? 'Verified the result' : 'Checked tool result';
  }

  function groupedTechnicalEvents(events) {
    const groups = [];
    const byKey = new Map();
    events.forEach(event => {
      const kind = eventType(event);
      const heading = technicalHeading(event, kind);
      const label = eventLabel(event);
      const failed = event.is_error === true || kind === 'error';
      const key = `${kind}\u0000${failed ? '1' : '0'}\u0000${heading}\u0000${label}`;
      const existing = byKey.get(key);
      if (existing) { existing.count += 1; return; }
      const group = { kind, heading, label, failed, count: 1 };
      groups.push(group);
      byKey.set(key, group);
    });
    return groups;
  }

  function technicalSummary(events) {
    const tools = events.filter(event => eventType(event) === 'tool').length;
    const checks = events.filter(event => eventType(event) === 'tool_result' || eventType(event) === 'meta').length;
    const issues = events.filter(event => event.is_error === true || eventType(event) === 'error').length;
    const other = Math.max(0, events.length - tools - checks - issues);
    const parts = [];
    if (tools) parts.push(`${tools} tool ${tools === 1 ? 'run' : 'runs'}`);
    if (checks) parts.push(`${checks} ${checks === 1 ? 'check' : 'checks'}`);
    if (other) parts.push(`${other} ${other === 1 ? 'detail' : 'details'}`);
    if (issues) parts.push(`${issues} ${issues === 1 ? 'issue' : 'issues'}`);
    return parts.length ? `Worked through ${parts.join(' · ')}` : 'Technical details';
  }

  function elapsedLabel(startedAt, now) {
    const seconds = Math.max(0, Math.floor(((now == null ? Date.now() : now) - Number(startedAt || 0)) / 1000));
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes}m ${seconds % 60}s`;
  }

  function refreshElapsed() {
    const label = surface()?.querySelector('[data-code-elapsed]');
    if (label && state.running && state.runStartedAt) label.textContent = `Working · ${elapsedLabel(state.runStartedAt)}`;
  }

  function eventHtml(event, saved) {
    const kind = eventType(event);
    if (isTechnicalEvent(event)) {
      const failed = event.is_error === true;
      const heading = technicalHeading(event, kind);
      return `<div class="tc-code-technical${failed ? ' is-error' : ''}" data-code-kind="${esc(kind)}"${saved ? ' data-saved="true"' : ''}><i class="ph ph-${failed ? 'warning' : 'check-circle'}"></i><div><strong>${esc(heading)}</strong><code>${esc(eventLabel(event))}</code></div></div>`;
    }
    const label = eventLabel(event);
    const content = label.length <= MAX_PROGRESS_EVENT_CHARS
      ? `<span>${esc(label)}</span>`
      : `<span>${esc(`${label.slice(0, 360).trimEnd()}…`)}</span><details class="tc-code-progress-full"><summary>Show full update</summary><span>${esc(label)}</span></details>`;
    return `<div class="tc-code-event is-${esc(kind)}" data-code-kind="${esc(kind)}"${event.delta ? ' data-code-delta="true"' : ''}${saved ? ' data-saved="true"' : ''}><strong>${esc(eventKind(event))}</strong>${content}</div>`;
  }

  function finalReplyEvent(events, turn) {
    const explicit = events.filter(event => eventType(event) === 'final').at(-1);
    if (explicit) return explicit;
    if (turn && turn.ok) return events.filter(event => eventType(event) === 'say').at(-1) || null;
    return null;
  }

  function progressEvents(events, finalEvent) {
    const finalText = finalEvent ? eventLabel(finalEvent) : '';
    return events.filter(event => event !== finalEvent && !(finalText && eventType(event) === 'say' && eventLabel(event) === finalText));
  }

  function narrativeActivityHtml(events, saved) {
    const narrative = events.filter(event => !isTechnicalEvent(event));
    const progressIndexes = narrative
      .map((event, index) => ['insight', 'planning', 'say'].includes(eventType(event)) ? index : -1)
      .filter(index => index >= 0);
    if (progressIndexes.length <= MAX_VISIBLE_PROGRESS_EVENTS) {
      return narrative.map(event => eventHtml(event, saved)).join('');
    }
    const visibleProgress = new Set([
      progressIndexes[0],
      ...progressIndexes.slice(-(MAX_VISIBLE_PROGRESS_EVENTS - 1)),
    ]);
    const hiddenProgress = progressIndexes.filter(index => !visibleProgress.has(index));
    const hiddenAt = hiddenProgress[0];
    return narrative.map((event, index) => {
      if (index === hiddenAt) {
        const rows = hiddenProgress.map(hiddenIndex => eventHtml(narrative[hiddenIndex], saved)).join('');
        return `<details class="tc-code-progress-history"><summary>${hiddenProgress.length} earlier progress ${hiddenProgress.length === 1 ? 'note' : 'notes'}</summary><div>${rows}</div></details>`;
      }
      return hiddenProgress.includes(index) ? '' : eventHtml(event, saved);
    }).join('');
  }

  function technicalActivityHtml(events, saved) {
    if (!events.length) return '';
    const groups = groupedTechnicalEvents(events);
    const rows = groups.map(group => {
      const count = group.count > 1 ? `<span class="tc-code-tech-count">×${group.count}</span>` : '';
      return `<div class="tc-code-technical${group.failed ? ' is-error' : ''}" data-code-kind="${esc(group.kind)}"><i class="ph ph-${group.failed ? 'warning' : 'check-circle'}"></i><div><strong>${esc(group.heading)}${count}</strong><code>${esc(group.label)}</code></div></div>`;
    }).join('');
    const issueCount = events.filter(event => event.is_error === true || eventType(event) === 'error').length;
    const status = !saved && state.running && state.runStartedAt
      ? `<span data-code-elapsed>Working · ${esc(elapsedLabel(state.runStartedAt))}</span>`
      : 'Show details';
    return `<details class="tc-code-saved-activity${issueCount ? ' has-issues' : ''}"${saved ? ' data-saved="true"' : ''}><summary><span class="tc-code-activity-summary"><i class="ph ph-${issueCount ? 'warning' : 'terminal-window'}"></i>${esc(technicalSummary(events))}</span><span>${status}</span></summary><div class="tc-code-technical-log">${rows}</div></details>`;
  }

  function transcriptEvents(turn) {
    const events = [];
    const terminalTracker = { name: '' };
    String(turn && turn.transcript || '').split('\n').forEach(raw => {
      const line = raw.trim(); if (!line) return;
      let parsed = null;
      if (line.startsWith('{')) {
        try { parsed = JSON.parse(line); } catch (error) { parsed = null; }
      }
      const event = annotateTerminalEvent(parsed && parsed.fc ? { type: 'output', kind: parsed.fc, name: parsed.name || '', text: parsed.text || '', is_error: parsed.is_error === true, delta: parsed.delta === true } : { type: 'output', text: raw }, terminalTracker);
      const previous = events[events.length - 1];
      const priorSayText = events.filter(item => item.kind === 'say' && item.delta).map(item => item.text || '').join('');
      if (event.kind === 'say' && event.delta && previous && previous.kind === 'say' && previous.delta) previous.text += event.text;
      else if (event.kind === 'say' && !event.delta && priorSayText && eventLabel(event) === priorSayText) return;
      else if (eventLabel(event) && (isTechnicalEvent(event) || !previous || event.kind !== previous.kind || eventLabel(event) !== eventLabel(previous))) events.push(event);
    });
    return events;
  }

  function failureSummary(turn, events) {
    if (turn.ok) return String(turn.reason || '').trim() || 'Verified Code result';
    const labels = events.map(eventLabel);
    if (labels.some(label => /verification failed.*after fix attempts/i.test(label))) {
      return 'Thomas changed the project, but the final verification still failed after its repair attempts. Open the activity details for the failing check.';
    }
    if (labels.some(label => /tool loop stability issue|failed repeatedly/i.test(label))) {
      return 'Thomas got stuck repeating a project check and stopped before finishing.';
    }
    if (labels.some(label => /remoteprotocolerror|stream disconnected|incomplete chunked|connection.*closed/i.test(label))) {
      return 'The model connection ended before Thomas could finish. Retry this task.';
    }
    const structured = events.filter(event => eventType(event) === 'error').map(eventLabel).filter(Boolean).at(-1);
    if (
      structured
      && structured.length <= 240
      && !/[{}\r\n]|traceback|http\s*\d{3}|remoteprotocolerror/i.test(structured)
      && !/^agent loop exited|^exited \d+/i.test(structured)
    ) return structured;
    if (structured) return 'Thomas hit a technical problem and stopped before finishing. Open the technical details for the raw error.';
    return 'The Code task stopped before it finished.';
  }

  function artifactHtml(artifact) {
    const file = String(artifact.file || '');
    const url = `/api/evolve/agent/artifact/${encodeURIComponent(state.activeId)}/${file.split('/').map(encodeURIComponent).join('/')}`;
    const title = `<strong>${esc(file)}</strong><a href="${url}" target="_blank" rel="noopener">Open</a>`;
    if (artifact.kind === 'html') return `<section class="tc-code-artifact"><header>${title}</header><iframe src="${url}" sandbox="allow-scripts allow-forms allow-same-origin" title="Preview ${esc(file)}"></iframe></section>`;
    if (artifact.kind === 'image') return `<section class="tc-code-artifact"><header>${title}</header><img src="${url}" alt="Generated artifact ${esc(file)}"></section>`;
    // PDF/schematic artifacts preview inline too (parity with chat), not just a link.
    if (artifact.kind === 'pdf' || /\.pdf(?:$|[?#])/i.test(file)) return `<section class="tc-code-artifact"><header>${title}</header><iframe src="${url}#toolbar=0&navpanes=0&view=FitH" title="Preview ${esc(file)}"></iframe></section>`;
    if (/\.svg(?:$|[?#])/i.test(file)) return `<section class="tc-code-artifact"><header>${title}</header><img src="${url}" alt="Generated artifact ${esc(file)}"></section>`;
    return `<section class="tc-code-artifact is-link"><header>${title}</header><span>${esc(artifact.kind || 'artifact')} result</span></section>`;
  }

  function turnHtml(turn) {
    if (turn.role === 'user') return `<article class="tc-code-turn is-user"><div>${esc(turn.text)}</div></article>`;
    const changedCount = (turn.changed_files || []).filter(file => !isInternalResultPath(file)).length;
    const events = transcriptEvents(turn);
    const finalEvent = finalReplyEvent(events, turn);
    const activityEvents = progressEvents(events, finalEvent);
    const modelFinal = finalEvent ? eventLabel(finalEvent) : '';
    const staleLimitReply = /execution review|review limit|forbid(?:s|den)? (?:another|further) tool|no files were changed and verification/i.test(modelFinal);
    const reply = turn.ok
      ? (modelFinal && !staleLimitReply ? modelFinal : 'Finished the requested changes and passed Thomas’s verification.')
      : failureSummary(turn, events);
    const narrative = narrativeActivityHtml(activityEvents, true);
    const technicalEvents = activityEvents.filter(isTechnicalEvent);
    const resultCount = (turn.artifacts || []).filter(artifact => !isInternalResultPath(artifact.file)).length;
    return `<article class="tc-code-turn is-agent"><div class="tc-code-message-head"><span class="tc-code-avatar" aria-hidden="true"><i class="ph ph-robot"></i></span><strong>Thomas</strong><small>${esc(turn.model || 'Code')}</small><button class="tc-code-copy" data-code-copy-reply type="button" aria-label="Copy Thomas reply"><i class="ph ph-copy"></i></button></div><div class="tc-code-turn-body">${narrative}${technicalActivityHtml(technicalEvents, true)}<div class="tc-code-reply${turn.ok ? '' : ' is-error'}">${esc(reply)}</div>${changedCount || resultCount ? `<div class="tc-code-result-note">${changedCount ? `<span><i class="ph ph-files"></i>${changedCount} file${changedCount === 1 ? '' : 's'} changed</span>` : ''}${resultCount ? `<span><i class="ph ph-browser"></i>${resultCount} result${resultCount === 1 ? '' : 's'} ready</span>` : ''}</div>` : ''}</div></article>`;
  }

  function transcriptScroller(root) {
    const transcript = root.querySelector('.tc-code-transcript');
    const layout = root.querySelector('.tc-code-layout');
    if (layout && transcript && layout.scrollHeight > layout.clientHeight && transcript.scrollHeight <= transcript.clientHeight) return layout;
    return transcript;
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

  function pushLiveEvent(event) {
    annotateTerminalEvent(event, {
      get name() { return state.terminalTool; },
      set name(value) { state.terminalTool = value; },
    });
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
    if (isTechnicalEvent(event)) {
      const activity = surface()?.querySelector('#tc-code-live-technical');
      if (activity) activity.innerHTML = technicalActivityHtml(state.liveEvents.filter(isTechnicalEvent), false);
      else render();
    } else {
      const progressCount = state.liveEvents.filter(item => !isTechnicalEvent(item) && ['insight', 'planning', 'say'].includes(eventType(item))).length;
      if (progressCount > MAX_VISIBLE_PROGRESS_EVENTS) {
        render();
        const nextTranscript = transcriptScroller(surface());
        if (nearBottom && nextTranscript) nextTranscript.scrollTop = nextTranscript.scrollHeight;
        return;
      }
      if (replaceLast && list.lastElementChild) list.lastElementChild.outerHTML = eventHtml(state.liveEvents[state.liveEvents.length - 1], false);
      else list.insertAdjacentHTML('beforeend', eventHtml(event, false));
      trimLiveEventDom(list);
    }
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
      if (state.running) parkActiveRun();
      return true;
    }
    recordError(null, 'Finish the pending Code approval or steering update before switching.');
    return false;
  }

  function clearContextState() {
    closeSource();
    finishBusy();
    state.activeId = '';
    state.conversation = null;
    state.liveEvents = [];
    state.changes = [];
    state.tree = [];
    state.treePath = '';
    state.artifacts = [];
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
      state.runStatus = data.persistence_confirmed === true ? (data.outcome || 'completed') : 'failed';
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

  function render() {
    if (!adapterActive) return;
    const root = surface(); if (!root) return;
    const savedRenderState = captureRenderState(root);
    const statusLabels = { ready: 'Ready', working: 'Working', stopping: 'Stopping', approval: 'Approval required', completed: 'Completed', noop: 'No changes made', stopped: 'Stopped', disconnected: 'Disconnected', failed: 'Needs attention' };
    const turns = state.conversation && Array.isArray(state.conversation.turns) ? state.conversation.turns : [];
    const liveFinalEvent = finalReplyEvent(state.liveEvents);
    const liveActivityEvents = progressEvents(state.liveEvents, liveFinalEvent);
    const liveNarrative = narrativeActivityHtml(liveActivityEvents, false);
    const liveErrors = state.liveEvents.filter(event => eventType(event) === 'error');
    const liveReply = liveFinalEvent
      ? `<div class="tc-code-reply">${esc(eventLabel(liveFinalEvent))}</div>`
      : liveErrors.length ? `<div class="tc-code-reply is-error">${esc(failureSummary({ ok: false }, liveErrors))}</div>` : '';
    const liveTechnical = technicalActivityHtml(liveActivityEvents.filter(isTechnicalEvent), false);
    const liveTurn = state.running || state.liveEvents.length
      ? `<article class="tc-code-turn is-agent is-live" data-code-live-turn><div class="tc-code-message-head"><span class="tc-code-avatar" aria-hidden="true"><i class="ph ph-robot"></i></span><strong>Thomas</strong><small>Code</small></div><div class="tc-code-turn-body"><div id="tc-code-live-events" aria-live="polite">${liveNarrative}</div><div id="tc-code-live-technical">${liveTechnical}</div>${liveReply}</div></article>`
      : '<div id="tc-code-live-events" hidden></div><div id="tc-code-live-technical" hidden></div>';
    const visibleChanges = state.changes.filter(change => !isInternalResultPath(change.file));
    const changeRows = visibleChanges.map(change => `<article class="tc-code-change"><header><strong>${esc(change.file)}</strong><span><button data-code-keep="${esc(change.file)}">Keep</button><button data-code-revert="${esc(change.file)}">Revert</button></span></header><details><summary>View ${change.untracked ? 'new file' : 'diff'}</summary><pre>${esc(change.diff || (change.untracked ? 'New file' : 'No textual diff'))}</pre></details></article>`).join('');
    const treeRows = state.tree.slice(0, 120).map(row => row.kind === 'directory' ? `<li class="is-dir"><button data-code-tree-dir="${esc(row.path)}"><i class="ph ph-caret-right"></i>${esc(row.name)}</button></li>` : row.kind === 'file' ? `<li><button data-code-tree-file="${esc(row.path)}"><i class="ph ph-file-code"></i>${esc(row.name || row.path || '')}</button></li>` : `<li><i class="ph ph-file"></i>${esc(row.name || row.path || '')}</li>`).join('');
    const artifacts = [];
    const artifactKeys = new Set();
    turns.flatMap(turn => turn.artifacts || []).concat(state.artifacts).filter(artifact => !isInternalResultPath(artifact.file)).forEach(artifact => {
      const key = `${artifact.file || ''}\u0000${artifact.kind || ''}`;
      if (!artifactKeys.has(key)) { artifactKeys.add(key); artifacts.push(artifact); }
    });
    const artifactRows = artifacts.map(artifactHtml).join('');
    const hasResults = Boolean(state.pendingApproval || visibleChanges.length || artifacts.length || state.filePreview);
    const preview = state.filePreview ? `<section class="tc-code-file-preview"><header><strong>${esc(state.filePreview.path)}</strong><button data-code-file-close aria-label="Close file preview"><i class="ph ph-x"></i></button></header><pre>${esc(state.filePreview.content)}</pre></section>` : '';
    const approval = state.pendingApproval ? `<section class="tc-code-approval" role="alert"><strong>Approval required</strong><p>${esc(state.pendingApproval.summary)}</p><div><button data-code-approve ${state.approvalBusy ? 'disabled' : ''}>${state.approvalBusy ? 'Approving...' : 'Approve once'}</button><button data-code-approval-cancel ${state.approvalBusy ? 'disabled' : ''}>Cancel</button></div></section>` : '';
    const projectLabel = state.projectRoot.split(/[\\/]/).filter(Boolean).pop() || 'Choose a project';
    root.innerHTML = `<div class="tc-code-panel${state.drawerOpen ? ' is-drawer-open' : ''}" style="--tc-code-drawer-width:${clampDrawerWidth(state.drawerWidth)}px">
      <header class="tc-code-context"><button data-code-results-jump type="button" aria-expanded="${state.drawerOpen ? 'true' : 'false'}"><i class="ph ph-sidebar-simple"></i> Activity <small>${statusLabels[state.runStatus] || 'Ready'}</small>${hasResults ? '<span class="tc-code-activity-count" aria-hidden="true"></span>' : ''}</button></header>
      <div class="tc-code-layout">
        <section class="tc-code-transcript" aria-label="Code conversation"><div id="tc-code-turns">${turns.map(turnHtml).join('') || '<div class="tc-code-empty"><span class="tc-code-avatar" aria-hidden="true"><i class="ph ph-robot"></i></span><strong>What should we make?</strong><span>Describe the outcome in the composer below. Keep using this same conversation for changes, tests, and review.</span></div>'}</div>${liveTurn}</section>
        <aside class="tc-code-actions" aria-label="Code activity" aria-hidden="${state.drawerOpen ? 'false' : 'true'}"${state.drawerOpen ? '' : ' inert'}><section class="tc-code-rail-section"><div class="tc-code-section-title">Outputs</div>${approval}${preview}${artifactRows}${changeRows || (!preview && !artifactRows ? '<p class="tc-code-rail-empty">Previews, changed files, and proof will appear here without interrupting the conversation.</p>' : '')}${changeRows && !state.running ? `<button id="tc-code-checkpoint" class="tc-code-checkpoint" title="Commit these changes on a thomas-code/ branch">Checkpoint — commit these changes</button>` : ''}</section><section class="tc-code-rail-section tc-code-tree"><div class="tc-code-tree-head"><div class="tc-code-section-title">Files · ${esc(state.treePath || '/')}</div>${state.treePath ? '<button id="tc-code-tree-up">Up</button>' : ''}</div><ul>${treeRows || '<li class="tc-code-muted">Choose a project beside Tools to browse its files.</li>'}</ul></section><form id="tc-code-steer-form" class="tc-code-steer" ${state.running ? '' : 'hidden'}><label for="tc-code-steer">Steer Thomas</label><input id="tc-code-steer" name="message" required placeholder="Change direction…" ${state.steeringBusy ? 'disabled' : ''}><button ${state.steeringBusy ? 'disabled' : ''}>${state.steeringBusy ? 'Confirming…' : 'Apply'}</button><button type="button" id="tc-code-stop" title="Stop this run" ${state.steeringBusy ? 'disabled' : ''}>Stop</button></form></aside>
      </div></div>`;
    const activityDrawer = root.querySelector('.tc-code-actions');
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
    root.querySelector('[data-code-approve]')?.addEventListener('click', () => { void safely(approvePending, 'Approval could not be completed.'); });
    root.querySelector('[data-code-approval-cancel]')?.addEventListener('click', () => { state.pendingApproval = null; state.pendingRequest = null; state.runStatus = 'stopped'; pushLiveEvent({ type: 'stopped', text: 'Approval cancelled. No Code action was run.' }); render(); });
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
    updateProjectButton();
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
    const token = lifecycle().contextToken(state);
    await Promise.all([loadChanges({ token, deferRender: true }), loadTree('', { token, deferRender: true })]);
    if (!(options && options.deferRender)) render();
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

  async function newConversation(projectRoot) {
    if (!canSwitchContext()) return false;
    const epoch = state.contextEpoch + 1;
    state.contextEpoch = epoch;
    const context = host().getContext ? host().getContext() : {};
    const requestedRoot = String(projectRoot == null ? state.projectRoot : projectRoot).trim();
    const response = await fetch('/api/evolve/agent/conversations/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_root: requestedRoot || undefined, ...lifecycle().requestSettings(context) }) });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Could not create Code task.');
    if (epoch !== state.contextEpoch) return false;
    clearContextState();
    state.activeId = data.conversation.id;
    state.conversation = data.conversation;
    state.projectRoot = data.conversation.project_root || requestedRoot;
    try { localStorage.setItem('thomas_code_project_root', state.projectRoot); }
    catch (error) { recordError(error, 'Project selection could not be saved for the next session.'); }
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

  function finishBusy() { state.running = false; host().setBusy && host().setBusy(false); updateProjectButton(); }
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
    else state.filePreview = data;
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
  }
  catch (error) { recordError(error, 'The saved Code project could not be loaded.'); }
  try {
    const savedDrawerWidth = Number(localStorage.getItem('thomas_code_drawer_width'));
    if (Number.isFinite(savedDrawerWidth)) state.drawerWidth = clampDrawerWidth(savedDrawerWidth);
  } catch (error) { recordPreferenceWarning(error, 'The saved activity drawer width could not be loaded.'); }

  function updateProjectButton() {
    const button = document.getElementById('tc-code-project-btn');
    if (!button) return;
    const span = button.querySelector ? button.querySelector('span') : null;
    const label = state.projectRoot.split(/[\\/]/).filter(Boolean).pop() || 'Project';
    if (span) span.textContent = label;
    button.title = state.projectRoot || 'Choose project folder';
    button.disabled = state.running || state.approvalBusy || state.steeringBusy;
  }

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
    updateProjectButton();
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
    enter: async () => { adapterActive = true; updateProjectButton(); render(); await refresh(); await adoptOrphanRun(); },
    leave,
    refresh,
    renderHistory,
    newConversation: () => safely(newConversation, 'Could not create the Code task.'),
    pickProject: () => safely(pickProject, 'Could not choose the project folder.'),
    send: (message, context) => safely(() => send(message, context), 'The Code task failed unexpectedly.'),
    stop: () => { void safely(stop, 'Could not stop the Code task.'); },
    isBusy: () => state.running || Boolean(state.finishing),
  });
})();
