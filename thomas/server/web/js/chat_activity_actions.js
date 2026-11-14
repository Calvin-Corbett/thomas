/* Chat activity actions. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {

    // A card with a real delegation behind it has a durable update history to
    // show, whether or not that delegation is a Thomas project with a Build
    // conversation. Both the view (the updates panel) and this module (fetch +
    // refresh) key off the same test, so a worker card never renders a panel it
    // then leaves empty.
    function _recordedCard(a) {
      return (a && a.steps || []).some(s => s && s.kind === 'handoff' && s.id);
    }

    // Is another read of the recorded history owed right now? A first read that
    // failed transiently must not strand the card for good: detailRetryAt was
    // only ever honoured by the delegation poll, and that loop runs solely while
    // a task is running, so a SETTLED card whose one read failed said "task
    // history is temporarily unavailable" forever and never asked again — not
    // even when the card was opened. A record the server says is gone sets the
    // backoff to never, so this stays false for it.
    function _detailReadDue(a) {
      if (!a || a.detailLoading) return false;
      // A timeline assembled from only SOME of the card's sources is not a
      // finished read — the card is holding part of the run — so it is owed
      // another one once the backoff passes, exactly like a read that brought
      // nothing back at all.
      if (a.timeline && !a.detailPartial) return false;
      if (!a.detailUnavailable && !a.detailPartial) return true;
      return Date.now() >= (a.detailRetryAt || 0);
    }

    // One recorded line's identity: the server stamps every transition, and the
    // pair is what distinguishes it from the next line on a re-read.
    const _stepKey = s => String((s && s.at) || '') + '\u0000' + String((s && s.summary) || '');

    // Fetch the durable step timeline for the card's execution(s).
    async function fetchActivityDetail(idx) {
      const isCurrent = deps.captureConversation();
      const a = deps.state.messages[idx] && deps.state.messages[idx].activity; if (!a || a.detailLoading) return;
      const sid = deps.state.sessionId; if (!sid) return;
      const handoffs = (a.steps || []).filter(s => s.kind === 'handoff' && s.id);
      if (!handoffs.length) return;
      a.detailLoading = true;
      // Only show the "Loading…" state on the FIRST fetch; live refreshes are
      // quiet so the timeline updates without flicker.
      if (!a.timeline && a.expanded) renderActivity(idx);
      // Collected OUTSIDE the try. A card can have several sources, and a throw
      // reading a later one carried everything already read out of scope with
      // it — the card fell back to "temporarily unavailable" while holding a
      // complete answer from the source that did reply.
      const merged = [];
      let tried = 0, missing = 0, read = 0;
      try {
        for (const step of handoffs) {
          tried++;
          const r = await fetch('/api/v2/chat/session/' + encodeURIComponent(sid) + '/delegations/' + encodeURIComponent(step.id) + '/detail');
          if (!r.ok) { if (r.status === 404) missing++; continue; }
          const d = await r.json();
          if (!isCurrent()) { a.detailLoading = false; return; }
          if (d && d.ok && Array.isArray(d.steps)) {
            read++;
            const label = handoffs.length > 1 ? (d.bot_name || 'worker') : '';
            d.steps.forEach(s => merged.push(label ? Object.assign({}, s, { summary: '[' + label + '] ' + (s.summary || '') }) : s));
          }
        }
      } catch (e) {}
      if (!isCurrent()) { a.detailLoading = false; return; }
      const fetched = read > 0;
      a.detailUnavailable = !fetched;
      // A record the server says is not there (deleting a chat sweeps its task
      // records) is not a transient read error: an old card would have promised
      // "temporarily unavailable" forever while retrying a 404 every 15s. Say
      // no history is kept for it, and stop asking.
      a.detailMissing = !fetched && tried > 0 && missing === tried;
      // Some sources answered and some did not. The card HAS history, so it was
      // never "unavailable" and so said nothing about the gap: the silent
      // worker's lines were simply absent, under a heading counting the ones
      // that arrived, and the backoff was cleared so nothing asked again. A
      // record the server reports gone is excluded — asking cannot bring it back.
      a.detailPartial = fetched && (tried - read - missing) > 0;
      // …and a read that reached fewer sources than the card HAS must not
      // SHRINK the history either. Recorded transitions are append-only, so a
      // line already read stays true even when the source that produced it goes
      // quiet — replacing the merged list wholesale made a card holding two
      // workers' history drop one of them on a single bad poll, and a running
      // card does thirty polls an hour. This is keyed on the read itself and
      // not on detailPartial, because a source the server reports GONE is
      // deliberately not a part-read (asking again cannot bring it back) and
      // going quiet that way is the strongest case of all: a card that had
      // shown two workers' updates dropped to one, silently, under a heading
      // that then counted only the survivor.
      const incomplete = read < tried;
      if (incomplete && Array.isArray(a.timeline)) {
        const seen = new Set(merged.map(_stepKey));
        a.timeline.forEach(s => { const k = _stepKey(s); if (!seen.has(k)) { seen.add(k); merged.push(s); } });
      }
      merged.sort((x, y) => String(x.at || '').localeCompare(String(y.at || '')));
      if (fetched) a.timeline = merged;
      // A transient read error must not permanently hide updates from a live
      // card. Polling may retry after a pause; never clear older history.
      a.detailRetryAt = fetched && !a.detailPartial ? 0 : a.detailMissing ? Number.MAX_SAFE_INTEGER : Date.now() + 15000;
      a.detailLoading = false; if (a.expanded || _recordedCard(a)) renderActivity(idx);
    }

    // The refusal a steer can get is a fact about the task, so it is worded once
    // for every surface that has a steer box (js/steering_language.js). This card
    // used to answer every failure with "Couldn't reach the running task just
    // now." while discarding the server's reason, so a task that had already
    // finished read as a network problem.
    function steerFailureText(reason) {
      const raw = String(reason || '').trim();
      const shared = window.ThomasSteering;
      return shared ? shared.failureText(raw) : raw || 'Thomas could not be reached.';
    }

    async function steerActivity(idx, text) {
      const isCurrent = deps.captureConversation();
      const a = deps.state.messages[idx] && deps.state.messages[idx].activity; if (!a) return;
      const sid = deps.state.sessionId; if (!sid) return;
      const running = (a.steps || []).filter(s => s.kind === 'handoff' && s.status === 'running' && s.id);
      const note = String(text || '').trim();
      // A second submit while the first is in flight would queue the same
      // instruction on the ledger twice, and the loop would apply it twice.
      if (!running.length || !note || a.steerBusy) return;
      // What was typed lives on the activity: the delegation poll repaints this
      // card from state, so a draft or a reason held in the node alone was gone
      // at the next progress event.
      a.steerDraft = note; a.steerBusy = true; a.steerFailed = false;
      a.steerNote = 'Sending your update to this task…';
      renderActivity(idx, { force: true });
      let sent = 0; let reason = '';
      for (const step of running) {
        try {
          const r = await fetch('/api/v2/chat/session/' + encodeURIComponent(sid) + '/delegations/' + encodeURIComponent(step.id) + '/steer', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: note }),
          });
          let d = {};
          try { d = await r.json(); } catch (e) { d = {}; }
          if (r.ok && d && d.ok) { sent += 1; continue; }
          reason = reason || String((d && d.error) || ('HTTP ' + r.status));
        } catch (e) {
          reason = reason || 'Thomas could not be reached.';
        }
      }
      a.steerBusy = false;
      a.steerFailed = sent === 0;
      if (sent === 0) a.steerNote = 'Update not applied: ' + steerFailureText(reason);
      // Partly through is its own outcome: re-sending would double the update on
      // the worker that did take it, so the text is cleared either way and the
      // shortfall is stated rather than rounded up to success.
      else if (reason) { a.steerDraft = ''; a.steerNote = 'Update reached ' + sent + ' of ' + running.length + ' workers on this task. ' + steerFailureText(reason); }
      else { a.steerDraft = ''; a.steerNote = 'Update sent. Thomas will read it at the next safe step.'; }
      if (isCurrent()) renderActivity(idx, { force: true, refocus: true });
    }

    // Where the reader is inside the recorded-updates list. The card is rebuilt
    // from scratch on every poll, so without this an open history jumps back to
    // its oldest line every few seconds — unreadable exactly when a long task
    // has the most to say. Stay pinned to the newest line if that is where they
    // already were; stay put if they scrolled back through the history.
    function _updatesScroll(el) {
      const section = el.querySelector && el.querySelector('[aria-label="Task updates"]');
      if (!section) return null;
      return { top: section.scrollTop, atEnd: section.scrollHeight - section.clientHeight - section.scrollTop <= 8 };
    }

    // Which of the card's own controls the keyboard is resting on. The card is
    // rebuilt wholesale from innerHTML, and a running task rebuilds it every
    // three seconds, so every control in it is destroyed under whoever is
    // standing on one: the ✕ that stops the task, and the tab stop on the
    // updates panel that exists precisely so its scroll is reachable without a
    // pointer. Focus fell to the document body and the next Tab restarted from
    // the top of the page.
    //
    // The empty-history status line is in this list because _refocusTarget puts
    // the keyboard THERE: pressing "Try again" on a card with no history removes
    // the button and leaves that line in its place. A target this module hands
    // focus to has to be one it can find again, or the repaint that finally
    // delivers the read — the one paint the reader was waiting for — drops them
    // to the document body.
    const _FOCUS_KEYS = ['data-act-cancel', 'data-act-expand', 'data-act-retry-detail', 'data-act-status', 'data-open-build', 'data-artifact-toggle'];
    const _UPDATES_PANEL = '[aria-label="Task updates"]';
    function _focusedControl(el) {
      const active = typeof document === 'undefined' ? null : document.activeElement;
      if (!active || !active.hasAttribute || !el.contains || !el.contains(active)) return '';
      const key = _FOCUS_KEYS.find(k => active.hasAttribute(k));
      if (key) return '[' + key + ']';
      return active.getAttribute && active.getAttribute('aria-label') === 'Task updates' ? _UPDATES_PANEL : '';
    }

    // Where that focus goes after the repaint. The control is usually still
    // there. When it is not, it is because pressing it removed it — "Show all"
    // has just revealed the rest of the history, "Try again" is now reading,
    // ✕ is now a disabled spinner — so hand focus to the updates panel, which
    // is where the result of the press is written. Exactly one of the panel and
    // its status line is focusable at a time: the tab stop only exists once
    // there are updates to scroll, and the status line carries tabindex="-1"
    // for the empty case.
    function _refocusTarget(el, key) {
      if (!el.querySelector) return null;
      const same = el.querySelector(key);
      // The panel survives every repaint as an element; its TAB STOP does not.
      // That stop exists only while there are updates to scroll, so a paint
      // that emptied the list leaves the same section in place unable to hold
      // focus — and handing the keyboard to a div that cannot take it drops it
      // to the document body exactly as silently as handing it to a control
      // that is gone. Ask whether the target is still focusable, not whether it
      // is still there.
      const focusable = same && !same.disabled
        && (key !== _UPDATES_PANEL || !!(same.hasAttribute && same.hasAttribute('tabindex')));
      if (focusable) return same;
      const panel = el.querySelector(_UPDATES_PANEL);
      if (panel && panel.hasAttribute && panel.hasAttribute('tabindex')) return panel;
      return el.querySelector('[data-act-status]');
    }

    function renderActivity(idx, options) {
      const ref = deps.msgRefs[idx]; if (!ref || !ref.activityEl) return;
      // NEVER clobber the card while the user is typing a steer note in it —
      // the poll re-render was wiping the input mid-keystroke. Updates resume
      // the moment the box loses focus or the note is sent.
      //
      // EXCEPT when this repaint IS the answer to what they just sent (force).
      // Pressing Enter leaves the caret in the box, so the guard swallowed the
      // "Sending…" state and the outcome with it: the whole send was invisible.
      const focused = document.activeElement;
      const typingHere = Boolean(focused && focused.hasAttribute && focused.hasAttribute('data-steer-input') && ref.activityEl.contains(focused));
      if (typingHere && !(options && options.force)) return;
      const m = deps.state.messages[idx]; if (!m || !m.activity) { ref.activityEl.innerHTML = ''; return; }
      const wasScrolled = _updatesScroll(ref.activityEl);
      const wasFocused = _focusedControl(ref.activityEl);
      ref.activityEl.innerHTML = deps.activityHTML(m);
      // "Show all" reveals the OLDER updates, and they sit ABOVE the ones
      // already on screen. Pinning to the newest line there would land the
      // reader back on the same four they could already see, so the one
      // control that reaches the rest of the history would look dead.
      const toTop = !!m.activity.showAllUpdates; m.activity.showAllUpdates = false;
      const updates = ref.activityEl.querySelector && ref.activityEl.querySelector('[aria-label="Task updates"]');
      if (updates) updates.scrollTop = toTop ? 0 : (!wasScrolled || wasScrolled.atEnd) ? updates.scrollHeight : wasScrolled.top;
      // preventScroll: the transcript must not jump to this card because a
      // background poll handed its own ✕ back the focus it already had.
      if (wasFocused) { const again = _refocusTarget(ref.activityEl, wasFocused); if (again && again.focus) again.focus({ preventScroll: true }); }
      // Dispatched tasks have a durable update history: fetch it as soon as the
      // card is rendered, not only after someone discovers the disclosure.
      if (_recordedCard(m.activity) && _detailReadDue(m.activity) && deps.state.sessionId) void fetchActivityDetail(idx);
      const tog = ref.activityEl.querySelector('[data-act-toggle]');
      if (tog) tog.addEventListener('click', () => { m.activity.expanded = !m.activity.expanded; renderActivity(idx); if (m.activity.expanded && _detailReadDue(m.activity)) fetchActivityDetail(idx); });
      // "Latest 4 of 12" is a real control, not an instruction: the rest of the
      // history was reachable only by knowing the card header is clickable.
      const moreBtn = ref.activityEl.querySelector('[data-act-expand]');
      if (moreBtn) moreBtn.addEventListener('click', (e) => { e.stopPropagation(); m.activity.expanded = true; m.activity.showAllUpdates = true; renderActivity(idx); });
      // The retry the "temporarily unavailable" copy promises. Asking counts as
      // consent to skip the backoff; the repaint has to happen here, right after
      // the read starts, because fetchActivityDetail only repaints on its own
      // for a card already expanded with no history — without it the button
      // would sit there having visibly done nothing.
      const retryBtn = ref.activityEl.querySelector('[data-act-retry-detail]');
      if (retryBtn) retryBtn.addEventListener('click', (e) => {
        e.stopPropagation(); m.activity.detailRetryAt = 0;
        void fetchActivityDetail(idx); renderActivity(idx);
      });
      const steerForm = ref.activityEl.querySelector('[data-steer-form]');
      if (steerForm) steerForm.addEventListener('submit', (e) => { e.preventDefault(); const input = steerForm.querySelector('[data-steer-input]'); const val = input ? input.value.trim() : ''; if (val) { steerActivity(idx, val); } });
      const cancelBtn = ref.activityEl.querySelector('[data-act-cancel]');
      if (cancelBtn) cancelBtn.addEventListener('click', (e) => { e.stopPropagation(); cancelTask(idx); });
      const buildBtn = ref.activityEl.querySelector('[data-open-build]');
      if (buildBtn) buildBtn.addEventListener('click', (e) => { e.stopPropagation(); void window.ThomasCodeMode?.openConversation(buildBtn.dataset.openBuild); });
      const artTog = ref.activityEl.querySelector('[data-artifact-toggle]');
      if (artTog) artTog.addEventListener('click', (e) => { e.stopPropagation(); m.activity.artifactOpen = !m.activity.artifactOpen; renderActivity(idx); });
      ref.activityEl.querySelectorAll('[data-artifact-open]').forEach(button => {
        button.addEventListener('click', (e) => {
          e.stopPropagation();
          void deps.canvasRender(button.dataset.artifactUrl || '', button.dataset.artifactName || 'result', button.dataset.artifactKind || '');
        });
      });
      // A forced repaint replaced the very node the caret was in. Put the caret
      // back so the reason for a refusal can be acted on without hunting for the
      // box again, and so a second update can be typed straight away.
      if (options && options.refocus) {
        const box = ref.activityEl.querySelector('[data-steer-input]');
        if (box && !box.disabled && typeof box.focus === 'function') {
          box.focus();
          const end = String(box.value || '').length;
          if (typeof box.setSelectionRange === 'function') box.setSelectionRange(end, end);
        }
      }
      // Completion events repaint this card but never repainted the bubble below it, so "On it — this is running now…" stayed the transcript's last line until a full re-render. Repaint once per settled wording (_settledStatusText) — not per poll, which would wipe an in-progress text selection for no visual change.
      if (!m.streaming && ref.bubbleEl) { const st = deps._settledStatusText(m); if (st !== null && m._settledRendered !== st) { m._settledRendered = st; ref.bubbleEl.innerHTML = deps.bubbleInner(m); } }
    }

    async function requestTaskCancel(sessionId, executionId) {
      const url = '/api/v2/chat/session/' + encodeURIComponent(sessionId) + '/delegations/' + encodeURIComponent(executionId) + '/cancel';
      const response = await fetch(url, { method: 'POST', headers: { Accept: 'application/json' } });
      let payload;
      try { payload = await response.json(); }
      catch (error) { throw new Error('Thomas returned an unreadable cancellation response (HTTP ' + response.status + ')'); }
      if (!response.ok || payload.ok !== true) throw new Error(String(payload.error || ('HTTP ' + response.status)));
      return payload;
    }

    async function cancelTask(idx) {
      return window.ThomasChatTurnFlow.cancelTask({
        state: deps.state, captureConversation: deps.captureConversation, requestTaskCancel, reportFriction: deps.reportFriction, renderActivity, canvasStop: deps.canvasStop, setExternalBusy: deps.setExternalBusy,
        getController: () => deps.abortController,
      }, idx);
    }

    function isChatBusy() {
      return !!deps.state.streaming || window.ThomasChatTurnFlow.runningTaskMessageIndexes(deps.state.messages).length > 0;
    }

    async function stopChat() {
      const indexes = window.ThomasChatTurnFlow.runningTaskMessageIndexes(deps.state.messages);
      if (indexes.length) await Promise.all(indexes.map(cancelTask));
      else if (deps.abortController) deps.abortController.abort();
    }

    function addToolStep(idx, name) { const a = deps.state.messages[idx].activity; if (!a) return; a.steps.push({ kind: 'tool', label: String(name || 'tool'), status: 'running' }); renderActivity(idx); }

    function finishToolStep(idx, ok) { const a = deps.state.messages[idx].activity; if (!a) return; for (let i = a.steps.length - 1; i >= 0; i--) { if (a.steps[i].kind === 'tool' && a.steps[i].status === 'running') { a.steps[i].status = ok === false ? 'failed' : 'completed'; break; } } renderActivity(idx); }

    function _completionVerified(row) {
      const proof = String((row && row.proof_status) || '').toLowerCase();
      return !!(row && row.receipt && row.receipt.ok === true && (proof === 'verified' || proof === 'attached'));
    }

    function _mergeArtifacts(activity, row) { window.ThomasChatTurnFlow.mergeArtifacts(activity, row); }

    function _maybeCollapseActivity(activity) {
      const handoffs = (activity.steps || []).filter(step => step && step.kind === 'handoff');
      const expected = Math.max(1, Number(activity.expectedHandoffCount || 1));
      if (handoffs.length >= expected && handoffs.every(step => step.status === 'completed' || step.status === 'failed')) {
        activity.expanded = false;
      }
    }

    function _settleActivityForReply(activity) {
      const handoffs = (activity.steps || []).filter(step => step && step.kind === 'handoff');
      if (!handoffs.length) activity.expanded = false;
      else _maybeCollapseActivity(activity);
    }

    function _canvasReviewed(row, done) {
      return !!(done && _completionVerified(row) && String(row.canvas_review_status || '').toLowerCase() === 'passed' && String(row.canvas_html || '').trim());
    }
    return { _recordedCard, _detailReadDue, _focusedControl, _refocusTarget, fetchActivityDetail, steerActivity, renderActivity, requestTaskCancel, cancelTask, isChatBusy, stopChat, addToolStep, finishToolStep, _completionVerified, _mergeArtifacts, _maybeCollapseActivity, _settleActivityForReply, _canvasReviewed };
  }
  window.ThomasChatActivityActions = { create };
})();
