/* Thomas chat shell — turn flow (loaded by chat.html as a classic script).
 *
 * Two jobs, both about what happens to a chat turn when the shell is not idle:
 *
 * 1. THE MID-REPLY SEND QUEUE. chat.html's send() used to open with
 *    `if (!text || state.streaming) return;` — Enter during a streaming reply
 *    was silently dropped: no bubble, no note, no send after completion, and
 *    the composer kept the text under an active-looking arrow (measured
 *    2026-08-05, w2-chat-followup-correction). Now a mid-reply send renders
 *    its bubble immediately with a visible "Queued" note and auto-sends, in
 *    order, as each reply finishes. The /classic shell has its own equivalent
 *    (js/runtime/011_chat_games_02.js pendingSendQueue) for its own send path;
 *    this module is the unified shell's — same contract, this surface's wiring.
 *
 * 2. DELEGATION-CARD RESTORE CLASSIFICATION. When a chat is revisited, the
 *    task activity card must come back for running AND settled tasks. The
 *    shared helpers here decide which delegation rows belong on the card,
 *    what each step looks like, and where the card attaches — with ONE
 *    terminal-state vocabulary, aligned with the server
 *    (thomas/server/chat_delegation_session.py _TERMINAL_TASK_STATES). The old
 *    inline list in chat.html missed 'verified' and 'abandoned', so a
 *    verified task could be "restored" as running forever and a failed one
 *    not at all.
 *
 * Pure helpers take plain data so the node harness (tests/web_node/
 * chat_shell_send_queue.mjs, chat_task_card_revisit_restore.mjs) can drive
 * them without a browser.
 */
(function () {
  'use strict';

  // Server truth plus the synonym states other emitters use
  // ('succeeded'/'passed'/'error'/'blocked' appear in streamed events).
  var TERMINAL_STATES = ['completed', 'verified', 'done', 'succeeded', 'passed',
    'failed', 'error', 'blocked', 'abandoned', 'cancelled', 'canceled'];
  var FAILED_STATES = ['failed', 'error', 'blocked', 'abandoned'];
  var CANCELLED_STATES = ['cancelled', 'canceled'];

  function rowState(row) {
    return String((row && (row.state || row.status)) || '').trim().toLowerCase();
  }
  function isTerminalDelegationState(value) {
    return TERMINAL_STATES.indexOf(String(value || '').trim().toLowerCase()) !== -1;
  }
  // Map a delegation row to an activity-card step status. Anything the server
  // does not call terminal is running — never the other way around.
  function delegationStepStatus(row) {
    var st = rowState(row);
    if (FAILED_STATES.indexOf(st) !== -1) return 'failed';
    if (CANCELLED_STATES.indexOf(st) !== -1) return 'cancelled';
    if (TERMINAL_STATES.indexOf(st) !== -1) return 'completed';
    return 'running';
  }
  function runningTaskMessageIndexes(messages) {
    var indexes = [];
    (messages || []).forEach(function (message, index) {
      if ((message.activity && message.activity.steps || []).some(function (step) {
        return step.kind === 'handoff' && step.status === 'running' && step.id;
      })) indexes.push(index);
    });
    return indexes;
  }
  async function cancelTask(deps, idx) {
    const { state, captureConversation, requestTaskCancel, reportFriction, renderActivity, canvasStop, setExternalBusy } = deps;
    const isCurrent = captureConversation();
    const controller = deps.getController(), sid = state.sessionId || '';
    const m = state.messages[idx]; const a = m && m.activity; if (!a) return;
    if (a.cancelling) return;
    reportFriction('task_cancelled', (a.steps.find(s => s.kind === 'handoff') || {}).label || 'running task');
    const running = a.steps.filter(s => s.kind === 'handoff' && s.status === 'running' && s.id);
    const executionIds = Array.from(new Set(running.filter(s => !s.cancelRequested).map(s => String(s.id))));
    if (running.length && !executionIds.length) return;
    a.cancelling = true; a.cancelError = ''; renderActivity(idx);
    if (!executionIds.length) {
      if (m.streaming && controller) controller.abort();
      a.steps.forEach(s => { if (s.status === 'running') s.status = 'cancelled'; });
      a.cancelled = true; a.cancelling = false; canvasStop('Cancelled.'); renderActivity(idx);
      return;
    }

    const results = await Promise.allSettled(executionIds.map(id => requestTaskCancel(sid, id)));
    if (!isCurrent()) return;
    const cancelledIds = new Set(executionIds.filter((_id, index) => results[index].status === 'fulfilled'));
    a.steps.forEach(s => { if (s.status === 'running' && cancelledIds.has(String(s.id))) { s.cancelRequested = true; s.label = 'Stopping…'; } });
    if (cancelledIds.size) {
      if (m.streaming && controller) controller.abort();
    }
    const failedCount = executionIds.length - cancelledIds.size;
    a.cancelError = failedCount ? `Couldn’t cancel ${failedCount === 1 ? 'the task' : failedCount + ' tasks'}. It may have already finished.` : '';
    a.cancelling = false; renderActivity(idx); setExternalBusy();
  }

  async function hydrateSelectedChat(deps, chat, selectionToken) {
    const sid = String((chat && chat.sessionId) || '');
    // A freshly allocated empty session has no persisted transcript to fetch yet.
    if (!sid || !Array.isArray(chat.msgs) || !chat.msgs.length) return false;
    const messages = deps.state.messages, before = deps.signature(messages);
    try {
      const response = await deps.fetch('/api/v2/chat/session/' + encodeURIComponent(sid), { cache: 'no-store' });
      if (!response.ok) return false;
      const payload = await response.json(), conversation = payload && payload.conversation;
      if (!conversation || !Array.isArray(conversation.messages)) return false;
      if (!deps.ownsSelection(chat, selectionToken, sid) || deps.state.streaming
        || deps.state.messages !== messages || deps.signature(messages) !== before) return false;
      chat.msgs = deps.mapMessages(conversation.messages, chat.model);
      deps.state.messages = chat.msgs.map(message => Object.assign({}, message));
      deps.paint();
      return true;
    } catch (error) { return false; }
  }

  // What a recorded status line should READ as. A Thomas-project transition
  // marks itself "Build update: …" so the server's humanizer leaves its real
  // text alone; that marker is provenance for the backend, not a sentence for
  // the card, which already heads its list with "Recorded in Build". A
  // "[worker]" tag is internal routing. Strip both — what is left is the update.
  function progressLabel(text) {
    return String(text == null ? '' : text).replace(/^\s*Build update:\s*/i, '').replace(/^\s*\[[^\]]+\]\s*/, '').trim();
  }

  function stepLabelFromRow(row) {
    return progressLabel((row && (row.last_progress || row.summary)) || '') || 'Working…';
  }

  function mergeArtifacts(activity, row) {
    const incoming = Array.isArray(row && row.artifacts) ? row.artifacts.slice() : [];
    if (!incoming.length && row && (row.artifact_url || row.artifact_name)) incoming.push({ id: String(row.execution_id || '') + ':primary', url: String(row.artifact_url || ''), name: String(row.artifact_name || 'result'), kind: String(row.artifact_kind || '') });
    if (!incoming.length) return;
    // Events and poll responses can identify the same verified file differently.
    const artifactKey = art => String(art.url || art.path || art.name || art.id || '');
    const byId = new Map((activity.artifacts || []).map(art => [artifactKey(art), art]));
    incoming.forEach(art => byId.set(artifactKey(art), art));
    activity.artifacts = Array.from(byId.values());
    // Refresh this task's ordering as well as its file metadata. Keep other
    // tasks in their existing slots so repeated polling does not shuffle them.
    const orderedKeys = Array.from(new Set(incoming.map(artifactKey)));
    const incomingKeys = new Set(orderedKeys);
    let next = 0;
    activity.artifacts = activity.artifacts.map(art => incomingKeys.has(artifactKey(art))
      ? byId.get(orderedKeys[next++]) : art);
    activity.artifact = activity.artifacts[0] || null;
  }

  function mergePartialArtifacts(activity, row) {
    var id = String((row && row.execution_id) || '');
    if (!id) return;
    var retained = (activity.partialArtifacts || []).filter(function (art) { return art.execution_id !== id; });
    var status = delegationStepStatus(row);
    var prefix = '/deliverable/' + encodeURIComponent(id) + '/';
    var incoming = (status === 'failed' || status === 'cancelled') && Array.isArray(row.partial_artifacts) ? row.partial_artifacts : [];
    incoming.forEach(function (art) {
      if (!art || art.status !== 'unverified' || !String(art.url || '').startsWith(prefix) || !String(art.url).endsWith('?download=1')) return;
      if (!retained.some(function (existing) { return existing.url === art.url; })) retained.push(Object.assign({}, art, { execution_id: id }));
    });
    activity.partialArtifacts = retained;
  }

  function partialArtifactsHTML(activity, esc) {
    var artifacts = activity.partialArtifacts || [];
    if (!artifacts.length) return '';
    return '<section data-partial-artifacts aria-label="Partial files not verified" style="margin-top:8px;max-width:420px;font-size:12px;color:var(--c-muted);">'
      + '<strong>Partial files — not verified</strong><p style="margin:4px 0;">These files may be incomplete.</p>'
      + artifacts.map(function (art) {
        return '<a href="' + esc(art.url) + '" download style="display:block;padding:6px 0;overflow-wrap:anywhere;">Download ' + esc(art.name || art.path || 'partial file') + '</a>';
      }).join('') + '</section>';
  }

  // Which rows belong on this chat's card, what each one's step looks like,
  // and where the card attaches (the last assistant bubble; -1 = none yet).
  function planDelegationRestore(rows, sessionId, messages) {
    var sid = String(sessionId || '');
    var steps = [];
    var anyRunning = false;
    var scopedRows = [];
    (Array.isArray(rows) ? rows : []).forEach(function (row) {
      if (!row || String(row.session_id || '') !== sid) return;
      var id = String(row.execution_id || row.id || '');
      if (!id) return;
      scopedRows.push(row);
      var status = delegationStepStatus(row);
      if (status === 'running') anyRunning = true;
      steps.push({
        kind: 'handoff',
        id: id,
        worker: String(row.bot_name || row.specialist_id || 'worker'),
        label: stepLabelFromRow(row),
        status: status,
        buildId: String((row.runtime_profile && row.runtime_profile.build_conversation_id) || ''),
      });
    });
    var anchorIdx = (Array.isArray(messages) ? messages.length : 0) - 1;
    while (anchorIdx >= 0 && messages[anchorIdx].role !== 'assistant') anchorIdx -= 1;
    return { steps: steps, anyRunning: anyRunning, anchorIdx: anchorIdx, rows: scopedRows };
  }

  // Fold a restore plan into a message's activity. A running row re-attaches
  // live (status + fresh label); a settled row never overwrites a richer step
  // that is already on the card (e.g. the verified restore's "Verified <name>").
  function mergeRestoredSteps(activity, plan) {
    activity.steps = activity.steps || [];
    plan.steps.forEach(function (planned) {
      var existing = activity.steps.find(function (s) { return s.kind === 'handoff' && s.id === planned.id; });
      if (existing) {
        if (planned.status === 'running') { existing.status = 'running'; existing.label = planned.label; }
        if (!existing.worker) existing.worker = planned.worker;
        if (planned.buildId) existing.buildId = planned.buildId;
      } else {
        activity.steps.push(planned);
      }
    });
    activity.expectedHandoffCount = Math.max(Number(activity.expectedHandoffCount || 0), plan.steps.length);
    if (plan.anyRunning) { activity.cancelled = false; activity.expanded = true; }
    (plan.rows || []).forEach(function (row) { mergePartialArtifacts(activity, row); });
    return activity;
  }

  // New Chat, boot, and the first send share one request per selection. A late
  // response may finish, but cannot bind a different conversation to its ID.
  function createSessionProvider(deps) {
    var pending = null;
    function sessionForSelection() {
      var selection = deps.getSelection();
      if (deps.state.sessionId) return Promise.resolve(deps.state.sessionId);
      if (pending && pending.selection === selection) return pending.promise;
      var entry = { selection: selection, promise: null };
      pending = entry;
      entry.promise = (async function () {
        try {
          var response = await deps.fetch('/api/session/new', { method: 'POST' });
          var data = response.ok ? await response.json() : null;
          if (selection !== deps.getSelection()) return null;
          var sid = data && (data.session_id || (data.data && data.data.session_id));
          if (!deps.state.sessionId && sid) {
            deps.state.sessionId = sid;
            deps.remember(sid);
          }
          return deps.state.sessionId;
        } catch (e) {
          return null; // The chat route can still allocate an ID when creation is unavailable.
        } finally {
          if (pending === entry) pending = null;
        }
      })();
      return entry.promise;
    }
    return function ensureSession(signal) {
      var promise = sessionForSelection();
      if (!signal) return promise;
      // Stop cancels the waiting turn immediately, while the shared session
      // request remains available to the next send in this conversation.
      return new Promise(function (resolve, reject) {
        function abort() { reject(new DOMException('Stopped', 'AbortError')); }
        if (signal.aborted) { abort(); return; }
        signal.addEventListener('abort', abort, { once: true });
        promise.then(function (sid) {
          signal.removeEventListener('abort', abort); resolve(sid);
        }, function (error) {
          signal.removeEventListener('abort', abort); reject(error);
        });
      });
    };
  }

  // The mid-reply send queue. `deps` are the shell's own closures, handed in
  // by chat.html so every rendered bubble is a real one, not a parallel copy.
  function create(deps) {
    var pending = {};
    var loaded = {};
    var serial = 0;
    var unloading = false;
    if (window.addEventListener) {
      window.addEventListener('pagehide', function () { unloading = true; });
      window.addEventListener('pageshow', function () { unloading = false; });
      window.addEventListener('storage', function (event) {
        var id = chatId();
        if (id && event.key === key(id)) { reconcile(id); redraw(); }
      });
    }
    function chatId() {
      var id = String(deps.state.activeChat || deps.state.sessionId || '');
      return id && id !== 'new' ? id : '';
    }
    function key(id) { return 'thomas_chat_queue:' + id; }
    function store() { try { return window.localStorage || localStorage; } catch (e) { return null; } }
    function list(id) { return pending[id] || (pending[id] = []); }
    function data(job) {
      return { id: job.id, text: job.text, docs: job.docs, images: job.images, selection: job.selection,
        retryRequired: !!job.retryRequired };
    }
    function load(id) {
      if (id && pending[''] && pending[''].length) {
        pending[''].slice().forEach(function (job) {
          if (deps.state.messages.indexOf(job.message) === -1) return;
          job.chat = id;
          if (!list(id).some(function (item) { return item.id === job.id; })) list(id).push(job);
          pending[''].splice(pending[''].indexOf(job), 1);
          save(job); status(job);
        });
      }
      if (!id || loaded[id]) return list(id);
      loaded[id] = true;
      var saved = rows(id);
      saved.forEach(function (row) {
        if (row && row.id && typeof row.text === 'string' && !list(id).some(function (job) { return job.id === row.id; })) list(id).push({
          id: row.id, text: row.text, docs: row.docs || [], images: row.images || [],
          chat: id, selection: row.selection || {}, persisted: true, retryRequired: !!row.retryRequired,
          error: row.retryRequired ? 'Send failed; your message is still queued.' : null,
          message: null, noteEl: null,
        });
      });
      return list(id);
    }
    function rows(id) {
      try { var result = JSON.parse(store().getItem(key(id)) || '[]'); return Array.isArray(result) ? result : []; }
      catch (e) { return []; }
    }
    function reconcile(id) {
      var saved = rows(id), jobs = list(id);
      jobs.slice().forEach(function (job) {
        var row = saved.find(function (item) { return item.id === job.id; });
        if (row) {
          if (row.retryRequired && !job.retryRequired) {
            job.retryRequired = true;
            job.error = 'Send failed; your message is still queued.';
            status(job);
          }
          return;
        }
        if (!job.persisted) return;
        // Another tab removed this job; do not redraw its bubble or resend it.
        removeVisible(job);
        jobs.splice(jobs.indexOf(job), 1);
      });
      saved.forEach(function (row) {
        if (!row || !row.id || typeof row.text !== 'string' || jobs.some(function (job) { return job.id === row.id; })) return;
        jobs.push({ id: row.id, text: row.text, docs: row.docs || [], images: row.images || [],
          chat: id, selection: row.selection || {}, persisted: true, retryRequired: !!row.retryRequired,
          error: row.retryRequired ? 'Send failed; your message is still queued.' : null,
          message: null, noteEl: null });
      });
      loaded[id] = true;
    }
    function change(job, update) {
      if (!job.chat) return false;
      var storage = store();
      if (!storage) return false;
      try {
        var current = rows(job.chat), index = current.findIndex(function (row) { return row.id === job.id; });
        if (update !== null && index === -1 && update !== 'add') return false;
        if (update === null) {
          if (index === -1) return false;
          current.splice(index, 1);
        }
        else if (update === 'add') {
          if (index !== -1) return false;
          current.push(data(job));
        } else current[index] = Object.assign({}, current[index], update);
        if (current.length) storage.setItem(key(job.chat), JSON.stringify(current));
        else storage.removeItem(key(job.chat));
        if (update === 'add' && rows(job.chat).length !== current.length) return false;
        return true;
      } catch (e) { return false; }
    }
    function save(job) { job.persisted = change(job, 'add'); return job.persisted; }
    function claim(job) {
      if (!job.persisted) return true;
      var row = rows(job.chat).find(function (item) { return item.id === job.id; });
      if (!row || (row.claim && row.claim.until > Date.now())) return false;
      var token = String(Date.now()) + ':' + Math.random();
      if (!change(job, { claim: { token: token, until: Date.now() + 60000 } })) return false;
      row = rows(job.chat).find(function (item) { return item.id === job.id; });
      if (!row || !row.claim || row.claim.token !== token) return false;
      job.claimToken = token;
      return true;
    }
    function visible(job) {
      var index = deps.state.messages.indexOf(job.message);
      return job.message && index !== -1 && deps.msgRefs[index] && deps.msgRefs[index].bubbleEl &&
        deps.msgRefs[index].bubbleEl.isConnected !== false;
    }
    function status(job) {
      if (!job.noteEl) return;
      var waiting = deps.canSendQueued && !deps.canSendQueued(job.selection);
      if (!waiting && job.error === 'The selected model cannot send right now.') job.error = '';
      if (job.noteEl.replaceChildren) job.noteEl.replaceChildren();
      job.noteEl.textContent = job.error ? 'Queued — ' + job.error : waiting
        ? 'Queued — waiting for ' + (job.selection.modelLabel || job.selection.modelId || 'the requested model') + ' to be available and selected'
        : 'Queued — will send when this reply finishes';
      var canOverride = !deps.state.streaming;
      if (list(job.chat).some(function (item) { return !item.persisted; }))
        job.noteEl.textContent += ' — a reload may lose queued work';
      function button(label, action) {
        var el = document.createElement('button'); el.type = 'button'; el.textContent = label;
        if (el.addEventListener) el.addEventListener('click', action);
        else el.onclick = action;
        if (job.noteEl.appendChild) job.noteEl.appendChild(el);
        else if (job.noteEl.insertAdjacentElement) job.noteEl.insertAdjacentElement('beforeend', el);
      }
      button('Remove', function () { removeJob(job); });
      if (canOverride) button('Send now', function () { handoff(job, true); });
      if (job.error) {
        var error = document.createElement('span'); error.textContent = job.error;
        job.noteEl.appendChild(error);
      }
    }
    function attachNote(job) {
      var ref = deps.msgRefs[deps.state.messages.indexOf(job.message)];
      if (!ref || !ref.bubbleEl || !ref.bubbleEl.insertAdjacentElement) return;
      if (job.noteEl && job.noteEl.remove) job.noteEl.remove();
      job.noteEl = document.createElement('div');
      job.noteEl.className = 'tc-queued-note';
      ref.bubbleEl.insertAdjacentElement('afterend', job.noteEl);
      status(job);
    }
    function forget(job) {
      var jobs = list(job.chat), index = jobs.indexOf(job);
      if (index < 0) return false;
      if (job.persisted && job.claimToken && !rows(job.chat).some(function (row) {
        return row.id === job.id && row.claim && row.claim.token === job.claimToken;
      })) return false;
      if (job.persisted && !change(job, null)) {
        job.error = 'Could not remove saved message; please try again.';
        status(job); return false;
      }
      jobs.splice(index, 1);
      if (job.noteEl && job.noteEl.remove) job.noteEl.remove();
      return true;
    }
    function accepted(job) {
      if (job.persisted && (!job.claimToken || !rows(job.chat).some(function (row) {
        return row.id === job.id && row.claim && row.claim.token === job.claimToken;
      }))) return;
      if (!forget(job)) return;
      job.sending = false; job.claimToken = null;
      list(job.chat).forEach(status);
    }
    function failed(job, reason) {
      job.sending = false;
      job.retryRequired = true;
      if (job.claimToken && rows(job.chat).some(function (row) {
        return row.id === job.id && row.claim && row.claim.token === job.claimToken;
      })) {
        // Read the latest queue so another tab's jobs survive this retry.
        var storage = store(), current = rows(job.chat);
        var savedIndex = current.findIndex(function (row) { return row.id === job.id; });
        if (storage && savedIndex !== -1) {
          var savedJob = current.splice(savedIndex, 1)[0];
          current.unshift(Object.assign({}, savedJob, { claim: null, retryRequired: true }));
          try { storage.setItem(key(job.chat), JSON.stringify(current)); }
          catch (e) { change(job, { claim: null, retryRequired: true }); }
        }
      }
      job.claimToken = null;
      job.error = reason || 'Could not send; please try again.';
      var jobs = list(job.chat), index = jobs.indexOf(job);
      if (index !== -1) { jobs.splice(index, 1); jobs.unshift(job); }
      status(job);
    }
    function removeVisible(job) {
      if (job.noteEl && job.noteEl.remove) job.noteEl.remove();
      var index = deps.state.messages.indexOf(job.message);
      if (index !== -1) {
        deps.state.messages.splice(index, 1);
        var ref = deps.msgRefs.splice(index, 1)[0];
        if (ref && ref.wrapEl && ref.wrapEl.remove) ref.wrapEl.remove();
        else if (ref && ref.bubbleEl && ref.bubbleEl.remove) ref.bubbleEl.remove();
      }
    }
    function removeJob(job) {
      if (!forget(job)) return false;
      removeVisible(job);
      return true;
    }
    function handoff(job, override) {
      if (unloading || (job.retryRequired && !override) || job.chat !== chatId() || deps.state.streaming || !visible(job)) return false;
      if (deps.canSendQueued && !deps.canSendQueued(override ? {
        profile: deps.state.profile, modelId: deps.state.modelId, modelLabel: deps.state.modelLabel,
      } : job.selection)) {
        if (override) job.error = 'The selected model cannot send right now.';
        status(job); return false;
      }
      if (job.sending || (job.persisted && !claim(job))) return false;
      job.sending = true; job.error = null; status(job);
      try {
        var request = deps.sendNow(job.text, {
          docs: job.docs, images: job.images,
          onAccepted: function () { accepted(job); },
          onFailed: function () { failed(job, 'Send failed; your message is still queued.'); },
        });
        if (request && typeof request.then === 'function') request.catch(function () {
          failed(job, 'Send failed; your message is still queued.');
        });
      } catch (e) { failed(job, 'Send failed; your message is still queued.'); }
      return true;
    }
    function redraw() {
      var id = chatId();
      load(id).forEach(function (job) {
        if (!visible(job)) {
          job.message = { role: 'user', text: job.text };
          deps.state.messages.push(job.message);
          deps.appendMessage(job.message);
        }
        if (!job.noteEl || job.noteEl.isConnected === false) attachNote(job);
        else status(job);
      });
    }
    function restoreQueued() {
      redraw();
      if (!deps.state.streaming) Promise.resolve().then(drainQueued);
    }
    function enqueue() {
      var state = deps.state, text = String(state.input || '').trim();
      if (!text) return false;
      var id = chatId(), jobs = load(id);
      var msg = { role: 'user', text: text };
      state.messages.push(msg);
      var job = { id: Date.now() + '-' + (++serial) + '-' + Math.random(), chat: id,
        text: text, docs: state.docs.slice(), images: state.images.slice(), message: msg, noteEl: null,
        selection: { profile: state.profile, modelId: state.modelId, modelLabel: state.modelLabel } };
      state.input = ''; deps.inputEl.value = '';
      state.docs = []; state.images = [];
      deps.syncView(); deps.appendMessage(msg); deps.renderAttachments();
      jobs.push(job); save(job); attachNote(job);
      jobs.forEach(status);
      deps.autosize(); deps.syncDynamic(); deps.scrollEnd();
      return true;
    }
    function drainQueued() {
      var jobs = load(chatId());
      jobs.forEach(status);
      if (unloading || deps.state.streaming || !jobs.length) return false;
      return handoff(jobs[0], false);
    }
    return { enqueue: enqueue, drainQueued: drainQueued, restoreQueued: restoreQueued, redraw: redraw,
      refreshQueuedNotes: function () { load(chatId()).forEach(status); },
      queuedCount: function () { return load(chatId()).length; } };
  }

  window.ThomasChatTurnFlow = {
    create: create,
    createSessionProvider: createSessionProvider,
    runningTaskMessageIndexes: runningTaskMessageIndexes,
    cancelTask: cancelTask,
    hydrateSelectedChat: hydrateSelectedChat,
    isTerminalDelegationState: isTerminalDelegationState,
    delegationStepStatus: delegationStepStatus,
    progressLabel: progressLabel,
    planDelegationRestore: planDelegationRestore,
    mergeRestoredSteps: mergeRestoredSteps,
    mergeArtifacts: mergeArtifacts,
    mergePartialArtifacts: mergePartialArtifacts,
    partialArtifactsHTML: partialArtifactsHTML,
  };
})();
