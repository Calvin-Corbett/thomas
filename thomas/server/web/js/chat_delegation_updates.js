/* Chat delegation updates. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {

    function handleHandoff(idx, evt) {
      const a = deps.state.messages[idx].activity; if (!a) return;
      const expected = Number(evt.runtime_profile && evt.runtime_profile.group_expected_count);
      if (Number.isFinite(expected) && expected > 0) a.expectedHandoffCount = Math.max(Number(a.expectedHandoffCount || 1), expected);
      if (evt.session_id) deps.state.sessionId = String(evt.session_id);
      const id = String(evt.execution_id || evt.specialist_id || ('h' + a.steps.length));
      let s = deps._handoffStep(a, id);
      if (!s) { s = { kind: 'handoff', id, worker: '', label: '', status: 'running' }; a.steps.push(s); }
      if (evt.runtime_profile?.build_conversation_id) s.buildId = String(evt.runtime_profile.build_conversation_id);
      if (evt.bot_name) s.worker = String(evt.bot_name); else if (evt.specialist_id && !s.worker) s.worker = String(evt.specialist_id);
      const sum = evt.last_progress || evt.summary || evt.task;
      if (sum) s.label = window.ThomasChatTurnFlow.progressLabel(sum);
      const t = evt.type;
      if (t === 'delegation_completed') s.status = deps._completionVerified(evt) ? 'completed' : 'running';
      else if (t === 'delegation_failed') s.status = 'failed';
      else if (evt.state) { const status = window.ThomasChatTurnFlow.delegationStepStatus(evt); s.status = status === 'completed' && !deps._completionVerified(evt) ? 'running' : status; }
      if (s.status === 'running') a.expanded = true;
      else deps._maybeCollapseActivity(a);
      if (t === 'delegation_completed' && s.status === 'running') s.label = 'Reviewing the result before presenting it';
      // The worker — not the chatbot — opens the Canvas, and only once it's
      // actually started building something renderable. Its real progress text
      // flows straight in; no fake placeholder.
      if (evt.is_canvas) {
        a.wantsCanvas = true;
        const reviewedDone = deps._canvasReviewed(evt, String(evt.canvas_status || '') === 'done' || s.status === 'completed');
        if (s.status === 'failed') deps.canvasStop((s.worker || 'The worker') + ' couldn’t finish this.');
        else if (String(evt.canvas_status || '').toLowerCase() === 'streaming' && evt.canvas_mode === 'construct' && String(evt.canvas_review_status || '').toLowerCase() === 'pending' && evt.canvas_shell) deps.canvasConstruct(id, evt.canvas_shell || '', evt.canvas_elements || [], false, '');
        else if (reviewedDone && evt.canvas_mode === 'construct') deps.canvasConstruct(id, evt.canvas_shell || '', evt.canvas_elements || [], true, evt.canvas_html || '');
        else if (reviewedDone) deps.canvasLiveHTML(evt.canvas_html || '', true);
      } else if (a.wantsCanvas && s.status === 'running') { /* review stays in the activity card */ }
      else if (a.wantsCanvas && s.status === 'failed') deps.canvasStop((s.worker || 'The worker') + ' couldn’t finish this.');
      // A non-visual deliverable (document/file) is presented as a click-to-preview
      // chip in the chat — it does NOT auto-open the Canvas. (Calvin, 2026-06-28)
      if (deps._completionVerified(evt)) deps._mergeArtifacts(a, evt);
      window.ThomasChatTurnFlow.mergePartialArtifacts(a, evt);
      deps.renderActivity(idx);
    }

    function handleTaskContract(idx, evt) {
      const a = deps.state.messages[idx].activity; if (!a) return;
      let s = a.steps.find(x => x.kind === 'phase' && x.id === 'task-contract');
      if (!s) { s = { kind: 'phase', id: 'task-contract', label: '', status: 'running' }; a.steps.push(s); }
      const t = evt.type; let label = '';
      if (t === 'task_definition') label = (evt.definition && (evt.definition.task_summary || evt.definition.good_result_definition)) || 'Defining a good result';
      else if (t === 'task_evaluation') { const st = String((evt.evaluation && evt.evaluation.status) || '').toLowerCase(); label = (evt.evaluation && evt.evaluation.summary) || (st === 'failed' ? 'Failed the quality bar' : 'Evaluation complete'); s.status = st === 'failed' ? 'failed' : 'completed'; }
      else { const p = String(evt.phase || '').toLowerCase(); label = p === 'defining' ? 'Defining a good result' : p === 'executing' ? 'Working the task' : p === 'evaluating' ? 'Evaluating the result' : label; if (p === 'complete' || p === 'completed') s.status = 'completed'; }
      if (label) s.label = label;
      deps.renderActivity(idx);
    }

    // Background delegations finish AFTER the chat stream closes (late events
    // dropped server-side). Poll the delegations endpoint to reconcile.
    function reconcileHandoff(idx, row) {
      const a = deps.state.messages[idx] && deps.state.messages[idx].activity; if (!a) return;
      const expected = Number(row.runtime_profile && row.runtime_profile.group_expected_count);
      if (Number.isFinite(expected) && expected > 0) a.expectedHandoffCount = Math.max(Number(a.expectedHandoffCount || 1), expected);
      const rid = String(row.execution_id || row.id || ''); if (!rid) return;
      // STRICT match by execution_id only: a turn reconciles ONLY the worker it
      // actually started, so a later turn never inherits an earlier task's result.
      const s = deps._handoffStep(a, rid); if (!s) return;
      if (row.runtime_profile?.build_conversation_id) s.buildId = String(row.runtime_profile.build_conversation_id);
      const rstate = String(row.state || row.status || '').toLowerCase();
      const status = window.ThomasChatTurnFlow.delegationStepStatus(row);
      s.status = status === 'completed' && !deps._completionVerified(row) ? 'running' : status;
      if (s.status === 'running') a.expanded = true;
      else deps._maybeCollapseActivity(a);
      if (row.bot_name && !s.worker) s.worker = String(row.bot_name);
      const sum = row.last_progress || row.summary; if (sum) s.label = window.ThomasChatTurnFlow.progressLabel(sum);
      if ((rstate === 'completed' || rstate === 'done' || rstate === 'succeeded' || rstate === 'passed') && s.status === 'running') s.label = 'Reviewing the result before presenting it';
      if (row.is_canvas) {
        a.wantsCanvas = true;
        const _cdone = String(row.canvas_status || '') === 'done' || s.status === 'completed';
        if (s.status === 'failed') deps.canvasStop((s.worker || 'The worker') + ' couldn’t finish this.');
        else if (String(row.canvas_status || '').toLowerCase() === 'streaming' && row.canvas_mode === 'construct' && String(row.canvas_review_status || '').toLowerCase() === 'pending' && row.canvas_shell) deps.canvasConstruct(rid, row.canvas_shell || '', row.canvas_elements || [], false, '');
        else if (deps._canvasReviewed(row, _cdone) && row.canvas_mode === 'construct') deps.canvasConstruct(rid, row.canvas_shell || '', row.canvas_elements || [], true, row.canvas_html || '');
        else if (deps._canvasReviewed(row, _cdone)) deps.canvasLiveHTML(row.canvas_html || '', true);
      } else if (a.wantsCanvas && s.status === 'running') { /* do not auto-open an unreviewed Canvas */ }
      else if (a.wantsCanvas && s.status === 'failed') deps.canvasStop((s.worker || 'The worker') + ' couldn’t finish this.');
      // A non-visual deliverable (document/file) is presented as a click-to-preview
      // chip in the chat — it does NOT auto-open the Canvas. (Calvin, 2026-06-28)
      if (deps._completionVerified(row)) deps._mergeArtifacts(a, row);
      window.ThomasChatTurnFlow.mergePartialArtifacts(a, row);
      // Proactively ANNOUNCE completion once: Thomas posts a model-authored "it's done"
      // bubble the moment the worker finishes, instead of going silent until the user's next
      // message. Fires once per step here; the backend's reported_to_chat_at guards globally.
      if (s.status === 'completed' || s.status === 'failed') queueCompletionAnnouncement(s, rid);
      deps.renderActivity(idx);
    }

    // Ask the backend to author (in Thomas's voice) a short "it's done" note for a finished
    // delegation and drop it into the thread as a Thomas bubble.
    async function announceCompletion(eid) {
      const isCurrent = deps.captureConversation();
      const sid = deps.state.sessionId; if (!sid || !eid) return false;
      try {
        const r = await fetch('/api/v2/chat/session/' + encodeURIComponent(sid) + '/delegations/' + encodeURIComponent(eid) + '/announce', { method: 'POST' });
        if (!r.ok) {
          console.warn('Thomas completion announcement failed', r.status);
          if (r.status === 404) {
            const failure = await r.json();
            if (isCurrent() && failure && failure.error === 'execution_not_found') return 'unavailable';
          }
          return false;
        }
        const d = await r.json();
        if (!isCurrent()) return false;
        if (d && d.ok && d.message) {
          const arts = Array.isArray(d.artifacts) ? d.artifacts.filter(a => a && (a.url || a.name)) : [];
          // The artifact lives on THIS "here it is" bubble now — remove it from
          // the earlier "on it" work card so it's presented once, not twice.
          if (arts.length) {
            for (let i = deps.state.messages.length - 1; i >= 0; i--) {
              const act = deps.state.messages[i] && deps.state.messages[i].activity;
              if (act && act.steps && act.steps.some(s => s.kind === 'handoff' && String(s.id) === String(eid))) {
                act.artifactMovedToAnnouncement = true; deps.renderActivity(i); break;
              }
            }
          }
          const msg = { role: 'assistant', text: String(d.message), model: deps.state.modelLabel || '', artifacts: arts, announceId: String(eid) };
          deps.state.messages.push(msg);
          deps.appendMessage(msg);
          deps.scrollEnd();
          // A playable/renderable result (game, chart, HTML) pops open on the
          // Canvas the moment Thomas says "here it is". Documents stay a chip.
          const playable = arts.find(a => String(a.kind || '').toLowerCase() === 'web' || /\.html?(?:$|[?#])/i.test(String(a.name || a.url || '')));
          if (playable && playable.url) { try { deps.canvasRender(playable.url, playable.name || 'result', playable.kind || 'web'); } catch (e) {} }
          return true;
        }
        if (d && d.ok && d.skipped === 'already_reported') return true;
        console.warn('Thomas completion announcement remains retryable', d && (d.skipped || d.error));
      } catch (e) {
        console.warn('Thomas completion announcement failed', e);
      }
      return false;
    }

    function queueCompletionAnnouncement(step, eid, attempt = 0) {
      const isCurrent = deps.captureConversation();
      if (!step || step._announced || step._announcementUnavailable || step._announcementPending || step._announcementRetry) return;
      step._announcementPending = true;
      announceCompletion(eid).then(done => {
        step._announcementPending = false;
        if (!isCurrent()) return;
        if (done === 'unavailable') {
          step._announcementUnavailable = true;
          step.label = 'The completion record is no longer available.';
          const idx = deps.state.messages.findIndex(message => message.activity && Array.isArray(message.activity.steps) && message.activity.steps.includes(step));
          if (idx >= 0) deps.renderActivity(idx);
          return;
        }
        if (done === true) {
          step._announced = true;
          return;
        }
        const delay = Math.min(30000, 1000 * (2 ** Math.min(attempt, 5)));
        step._announcementRetry = setTimeout(() => {
          step._announcementRetry = null;
          if (isCurrent()) queueCompletionAnnouncement(step, eid, attempt + 1);
        }, delay);
      });
    }

    async function pollDelegations(idx) {
      const isCurrent = deps.captureConversation();
      const sid = deps.state.sessionId; if (!sid) return;
      for (let i = 0; i < 400; i++) {
        if (!isCurrent()) return;
        const a = deps.state.messages[idx] && deps.state.messages[idx].activity;
        if (!a || a.cancelled || !a.steps.some(s => s.kind === 'handoff' && s.status === 'running')) return;
        // Poll fast while a canvas worker is actively drawing — both the live-HTML
        // mode and the element-streaming "construct" mode — so elements appear smoothly
        // and a slow canvas reconciles to "done" quickly instead of sitting on
        // "building…" for many seconds (the completion event is dropped after write_eof,
        // so this poll is the only thing that lands the final render). (chat sweep 2026-06-27)
        const fast = (deps.canvasState.mode === 'live' && deps.canvasState.live)
          || (deps.canvasState.mode === 'construct' && !deps.canvasState.done);
        await new Promise(r => setTimeout(r, fast ? 600 : 3000));
        if (!isCurrent()) return;
        try {
          const r = await fetch('/api/v2/chat/session/' + encodeURIComponent(sid) + '/delegations');
          if (r.ok) {
            const d = await r.json(); const rows = d.delegations || (d.data && d.data.delegations) || [];
            if (!isCurrent()) return;
            rows.forEach(row => reconcileHandoff(idx, row));
          }
        } catch (e) {}
        // Keep the card's recorded updates moving while it is collapsed — that
        // panel is the only place a running task says what it is doing — and
        // keep an expanded timeline fresh. Never clear a steer note mid-typing.
        const act = deps.state.messages[idx] && deps.state.messages[idx].activity;
        const typing = document.activeElement && document.activeElement.hasAttribute && document.activeElement.hasAttribute('data-steer-input');
        if (isCurrent() && act && !typing && !act.detailLoading &&
            (!act.detailUnavailable || Date.now() >= (act.detailRetryAt || 0)) &&
            (act.expanded || (act.steps || []).some(s => s.kind === 'handoff' && s.id))) deps.fetchActivityDetail(idx);
      }
    }
    return { handleHandoff, handleTaskContract, reconcileHandoff, announceCompletion, queueCompletionAnnouncement, pollDelegations };
  }
  window.ThomasChatDelegationUpdates = { create };
})();
