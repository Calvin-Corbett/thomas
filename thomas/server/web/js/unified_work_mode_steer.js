(function () {
  'use strict';

  // The Work card's live view of the delegated tasks a turn starts, and the
  // steer box on each running one. The Work adapter (unified_work_mode.js)
  // creates this once with its own state and helpers, the way it creates
  // unified_work_support.js, so chat.html loads this file before the adapter.
  function create({ state, request, surface, render, isActive, generation }) {
    function recordLiveTask(event) {
      const type = String(event.type || '');
      const id = String(event.execution_id || '').trim();
      if (!id) return;
      const index = state.liveTasks.findIndex(row => row.id === id);
      const current = index < 0 ? { id, status: 'running', detail: '', title: 'Running task' } : state.liveTasks[index];
      const status = type === 'delegation_completed' ? 'completed' : type === 'delegation_failed' ? 'failed' : 'running';
      const title = String(event.title || event.label || event.summary || event.task || event.specialist_id || current.title || 'Running task').slice(0, 100);
      const detail = String(event.last_progress || event.text || event.error || current.detail || '').slice(0, 240);
      const next = { ...current, title, detail, status };
      if (index < 0) state.liveTasks.push(next); else state.liveTasks[index] = next;
      if (state.liveTasks.length > 8) state.liveTasks.shift();
      if (isActive()) render();
    }

    async function restoreRunningTasks(expectedGeneration, sessionId) {
      if (!sessionId) return;
      try {
        const data = await request(`/api/v2/chat/session/${encodeURIComponent(sessionId)}/delegations`);
        if (!isActive() || expectedGeneration !== generation() || state.sessionId !== sessionId) return;
        const active = (data.delegations || []).filter(row => row.execution_id && !['completed', 'failed', 'cancelled', 'stopped'].includes(row.state)).map(row => ({
          id: String(row.execution_id), title: String(row.summary || row.specialist_id || 'Running task').slice(0, 100),
          detail: String(row.last_progress || 'Continuing this task…').slice(0, 240), status: 'running',
        })).slice(-8);
        active.forEach(task => { if (!state.liveTasks.some(row => row.id === task.id)) state.liveTasks.push(task); });
        if (active.length) render();
      } catch { /* A stale ledger must not hide the saved job conversation. */ }
    }

    // Every progress line repaints this whole surface from state, and a job can
    // have several tasks running at once (the live list holds up to eight). Only
    // the FIRST steer box was carried across that repaint, so a note being typed
    // into the second task's box was erased by the next progress event and the
    // caret was thrown out of it — while the task it was meant for kept running.
    // Each box keeps its own draft, keyed by the execution it steers.
    function captureSteerDrafts(root) {
      const active = document.activeElement;
      return [...(root?.querySelectorAll('[data-work-steer]') || [])].map(form => ({
        id: String(form.dataset?.workSteer || ''),
        text: form.querySelector('textarea')?.value || '',
        focused: Boolean(active && typeof form.contains === 'function' && form.contains(active)),
      })).filter(row => row.id && (row.text || row.focused));
    }

    function restoreSteerDrafts(root, drafts) {
      if (!drafts || !drafts.length) return;
      const forms = [...(root?.querySelectorAll('[data-work-steer]') || [])];
      drafts.forEach(draft => {
        const input = forms.find(form => String(form.dataset?.workSteer || '') === draft.id)?.querySelector('textarea');
        if (!input) return;
        // A box disabled mid-send is showing "Sending…". Its text is written back
        // anyway, the way the chat card does it: it shows what is on its way, and
        // it is still there to send again if the update comes back refused.
        input.value = draft.text;
        if (input.disabled || !draft.focused || typeof input.focus !== 'function') return;
        input.focus();
        const end = String(input.value || '').length;
        if (typeof input.setSelectionRange === 'function') input.setSelectionRange(end, end);
      });
    }

    // The adapter's render() repaints through this: the drafts are carried
    // across the new markup, and each new steer box is wired to its task.
    function paintKeepingSteerDrafts(root, paint) {
      const steerDrafts = captureSteerDrafts(root);
      paint();
      restoreSteerDrafts(root, steerDrafts);
      root.querySelectorAll('[data-work-steer]').forEach(form => form.addEventListener('submit', event => {
        event.preventDefault();
        void steerRunningTask(form.dataset.workSteer, form);
      }));
    }

    // The steer endpoint answers with machine tokens ("session_mismatch") and with
    // the ledger's own sentence naming a raw execution id. Neither is something to
    // show someone who just asked a running task to change course. The wording is
    // shared with the chat activity card's steer box (js/steering_language.js):
    // one endpoint vocabulary, one translation of it.
    function steerFailureText(message) {
      const raw = String(message || '').trim();
      const shared = window.ThomasSteering;
      return shared ? shared.failureText(raw) : raw || 'Thomas could not be reached.';
    }

    async function steerRunningTask(executionId, form) {
      const task = state.liveTasks.find(row => row.id === executionId && row.status === 'running');
      const text = String(form.querySelector('textarea')?.value || '').trim();
      if (!task || !state.sessionId || !text || state.steeringBusy) return;
      const sessionId = state.sessionId;
      const expectedGeneration = generation();
      task.steerError = '';
      state.steeringBusy = executionId;
      const button = form.querySelector('button[type="submit"]'); if (button) button.disabled = true;
      try {
        const data = await request(`/api/v2/chat/session/${encodeURIComponent(sessionId)}/delegations/${encodeURIComponent(executionId)}/steer`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text }),
        });
        if (data.action !== 'steer' || data.execution_id !== executionId) throw new Error('Thomas did not confirm that this task received the update.');
        if (expectedGeneration !== generation() || state.sessionId !== sessionId) return;
        task.detail = 'Update queued for this task. Thomas will read it at the next safe step.';
        state.steeringBusy = '';
        const visibleForm = [...(surface()?.querySelectorAll('[data-work-steer]') || [])]
          .find(row => row.dataset.workSteer === executionId);
        const input = visibleForm?.querySelector('textarea') || form.querySelector('textarea');
        if (input) input.value = '';
        if (isActive()) render();
      } catch (error) {
        if (expectedGeneration !== generation() || state.sessionId !== sessionId) return;
        state.steeringBusy = '';
        // The failure has to live on the task, not only in this form's DOM node:
        // every progress event re-renders the surface from state, so a message
        // written straight into the node vanished within a second of appearing,
        // leaving a cleared form and no reason why the update never landed.
        task.steerError = `Update not applied: ${steerFailureText(error.message)}`;
        const note = form.querySelector('[data-work-steer-error]');
        if (note) note.textContent = task.steerError;
        if (button) button.disabled = false;
        if (isActive()) render();
      }
    }

    // The turn's outcome, read from its tasks once the chat stream has ended.
    function finishRun() {
      state.runState = state.liveTasks.some(task => task.status === 'failed') ? 'failed' : 'completed';
      if (state.runState === 'failed') state.error = 'One or more tasks failed. Review the task status below.';
    }

    return {
      recordLiveTask,
      restoreRunningTasks,
      captureSteerDrafts,
      restoreSteerDrafts,
      paintKeepingSteerDrafts,
      steerFailureText,
      steerRunningTask,
      finishRun,
    };
  }

  window.ThomasWorkModeSteer = { create };
})();
