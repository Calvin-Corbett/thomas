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
  function stepLabelFromRow(row) {
    var raw = String((row && (row.last_progress || row.summary)) || '');
    return raw.replace(/^\s*\[[^\]]+\]\s*/, '').trim() || 'Working…';
  }

  // Which rows belong on this chat's card, what each one's step looks like,
  // and where the card attaches (the last assistant bubble; -1 = none yet).
  function planDelegationRestore(rows, sessionId, messages) {
    var sid = String(sessionId || '');
    var steps = [];
    var anyRunning = false;
    (Array.isArray(rows) ? rows : []).forEach(function (row) {
      if (!row || String(row.session_id || '') !== sid) return;
      var id = String(row.execution_id || row.id || '');
      if (!id) return;
      var status = delegationStepStatus(row);
      if (status === 'running') anyRunning = true;
      steps.push({
        kind: 'handoff',
        id: id,
        worker: String(row.bot_name || row.specialist_id || 'worker'),
        label: stepLabelFromRow(row),
        status: status,
      });
    });
    var anchorIdx = (Array.isArray(messages) ? messages.length : 0) - 1;
    while (anchorIdx >= 0 && messages[anchorIdx].role !== 'assistant') anchorIdx -= 1;
    return { steps: steps, anyRunning: anyRunning, anchorIdx: anchorIdx };
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
      } else {
        activity.steps.push(planned);
      }
    });
    activity.expectedHandoffCount = Math.max(Number(activity.expectedHandoffCount || 0), plan.steps.length);
    if (plan.anyRunning) { activity.cancelled = false; activity.expanded = true; }
    return activity;
  }

  // The mid-reply send queue. `deps` are the shell's own closures, handed in
  // by chat.html so every rendered bubble is a real one, not a parallel copy.
  function create(deps) {
    var pending = [];

    function attachNote(idx) {
      var ref = deps.msgRefs[idx];
      if (!ref || !ref.bubbleEl || !ref.bubbleEl.insertAdjacentElement) return null;
      var note = document.createElement('div');
      note.className = 'tc-queued-note';
      note.textContent = 'Queued — will send when this reply finishes';
      ref.bubbleEl.insertAdjacentElement('afterend', note);
      return note;
    }

    // Park the composer's current draft: the bubble renders NOW (with the
    // queued note), the composer clears, and the job waits for the stream end.
    function enqueue() {
      var state = deps.state;
      var text = String(state.input || '').trim();
      if (!text) return false;
      var msg = { role: 'user', text: text };
      state.messages.push(msg);
      var job = { text: text, docs: state.docs.slice(), images: state.images.slice(), message: msg, noteEl: null };
      state.input = ''; deps.inputEl.value = '';
      state.docs = []; state.images = [];
      deps.syncView(); deps.appendMessage(msg); deps.renderAttachments();
      job.noteEl = attachNote(state.messages.indexOf(msg));
      deps.autosize(); deps.syncDynamic(); deps.scrollEnd();
      pending.push(job);
      return true;
    }

    // Called from streamReal's finally: send the NEXT queued message, if any.
    // One per completion — its own finish drains the one after, keeping order.
    function drainQueued() {
      if (deps.state.streaming) return false;
      while (pending.length) {
        var job = pending.shift();
        if (job.noteEl && job.noteEl.remove) { try { job.noteEl.remove(); } catch (e) {} }
        // The transcript this was queued into is gone (chat switched, or
        // edit-and-resend truncated past it) — a bubble no longer on screen
        // must not fire into whatever conversation is open now.
        if (deps.state.messages.indexOf(job.message) === -1) continue;
        // The job's attachments ride with it; anything staged since stays too.
        deps.state.docs = job.docs.concat(deps.state.docs);
        deps.state.images = job.images.concat(deps.state.images);
        deps.renderAttachments();
        deps.sendNow(job.text);
        return true;
      }
      return false;
    }

    return {
      enqueue: enqueue,
      drainQueued: drainQueued,
      queuedCount: function () { return pending.length; },
    };
  }

  window.ThomasChatTurnFlow = {
    create: create,
    isTerminalDelegationState: isTerminalDelegationState,
    delegationStepStatus: delegationStepStatus,
    planDelegationRestore: planDelegationRestore,
    mergeRestoredSteps: mergeRestoredSteps,
  };
})();
