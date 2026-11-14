/* Build run stream. The mode supplies shared state and actions. */
(function () {
  'use strict';
  function create(deps) {


    function closeSource() {
      const source = deps.state.source;
      deps.state.source = null;
      if (source) source.close();
    }


    async function acceptStartedRun(data) {
      deps.adoptStartedConversation(data.conversation_id, data.project_root, data.run_id);
      // What this run's lead can take (pause, messages, questions).
      deps.controls?.applyControls?.(data);
      deps.state.actionLine = { words: 'Thomas is starting', at: Date.now(), conversationId: deps.state.activeId };
      deps.lifecycle().registerRunProof(deps.state, data.conversation_id, data.run_id);
      deps.state.retryRequest = null;
      deps.state.pendingApproval = null;
      deps.state.pendingRequest = null;
      if (data.run_state === 'completed' || data.run_state === 'persistence_failed') {
        // The same predicate the streaming `done` frame uses -- see
        // `terminalRunStatus`. This line used to spell the decision a second time
        // and read `data.outcome`, which is why a replayed conversational answer
        // landed on the badge as the raw word 'conversation'.
        deps.state.runStatus = deps.terminalRunStatus(data);
        const epoch = deps.state.contextEpoch;
        const runId = deps.state.runId;
        const proof = deps.state.runProof ? { ...deps.state.runProof } : null;
        const results = await Promise.allSettled([deps.loadConversation(data.conversation_id, { internal: true, epoch, deferRender: true }), deps.refresh({ throwOnError: true })]);
        const loaded = results[0].status === 'fulfilled' && results[0].value === true;
        const durable = data.persistence_confirmed === true && loaded && deps.state.contextEpoch === epoch && deps.state.runId === runId && deps.lifecycle().runIsDurable(deps.state.conversation, proof);
        if (durable) {
          deps.state.liveEvents = [];
          deps.state.artifacts = [];
          deps.state.runProof = null;
        } else {
          deps.state.runStatus = 'failed';
          deps.pushLiveEvent({ type: 'error', text: 'Thomas finished, but the durable Build reply could not be confirmed. Live evidence was preserved.' });
        }
        results.filter(result => result.status === 'rejected').forEach(result => deps.pushLiveEvent({ type: 'error', text: deps.errorText(result.reason, 'The Build result could not be refreshed.') }));
        window.ThomasCodeLiveView?.finishAction?.(deps.state, durable ? data : { ok: false }, false);
        finishBusy(); deps.render();
        // The replayed already-finished run has the same below-the-fold problem
        // finishRun documents: its durable turn just landed in a conversation the
        // reader is looking at, so land the viewport on it too.
        if (durable) deps.scrollTranscriptToNewest();
        // Thomas tests his own work before handing it over: a durable build that
        // produced a playable page gets auto-playtested, and the verdict +
        // recommendations land in the chat. Only for a real build (files
        // changed) so an explain/answer run is never tested.
        if (durable) void deps.safely(() => deps.maybeAutoPlaytest(), 'Could not start the automatic playtest.');
        return durable;
      }
      // Publish the accepted run identity before incremental activity arrives.
      deps.render();
      openStream();
      await deps.refresh();
      return true;
    }


    function openStream() {
      const previous = deps.state.source; deps.state.source = null; if (previous) previous.close();
      if (deps.state.running && deps.state.activeId && deps.state.actionLine?.conversationId !== deps.state.activeId) {
        deps.state.actionLine = { words: 'Thomas is starting', at: Date.now(), conversationId: deps.state.activeId };
        deps.render();
      }
      const source = new EventSource(deps.lifecycle().streamUrl(deps.state)); deps.state.source = source;
      deps.controls?.streamOpened?.();
      source.onmessage = event => {
        if (deps.state.source !== source) return;
        let payload; try { payload = JSON.parse(event.data); } catch (error) { payload = { type: 'text', text: event.data }; }
        // Every frame reaches the run's controls first: tool_started carries the
        // file paths and the helpers' briefs the agent roster is built from.
        if (payload && typeof payload === 'object') deps.controls?.observe?.(payload);
        if (payload && (payload.fc === 'tool_started' || payload.kind === 'tool_started')) return; // for watchers; its result is the row
        if (!deps.lifecycle().acceptEvent(deps.state, payload)) return;
        const action = deps.state.actionLine;
        if (action?.beforeDisconnect) {
          Object.assign(action, action.beforeDisconnect);
          delete action.beforeDisconnect;
          window.ThomasCodeLiveView?.paintExtras?.(deps.state);
        }
        if (payload.type === 'done' && payload.noop === true && !payload.text) payload.text = 'The process exited cleanly but made no file changes, so this Build task is not complete.';
        const replaced = deps.pushLiveEvent(payload); deps.appendLiveEvent(payload, replaced);
        if (payload.type === 'done') {
          const stopWasPending = deps.state.runStatus === 'stopping';
          window.ThomasCodeLiveView?.finishAction?.(deps.state, payload, stopWasPending);
          deps.state.artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : [];
          // A finished run may have written files the current preview origin was
          // not told about, so stop deriving URLs from it and ask again.
          deps.state.previewBase = null;
          deps.state.artifactDocs = {};
          deps.state.source = null;
          source.close();
          if (stopWasPending) {
            deps.state.runStatus = 'stopped';
            // Plain words for a deliberate click. This said "Stop confirmed
            // (process exit 1)." -- an exit code leaked into a sentence about a
            // clean user stop, and exit 1 reads as an error. The durable render
            // of the stopped turn is already honest; the live confirmation now
            // matches its register.
            const confirmation = { type: 'stopped', text: 'Stopped — Thomas is wrapping up the record.' };
            deps.pushLiveEvent(confirmation);
            deps.appendLiveEvent(confirmation, false);
          } else {
            deps.state.runStatus = deps.terminalRunStatus(payload);
          }
          deps.updateRunStatus();
          if (deps.state.steeringBusy) {
            finishBusy();
            return;
          }
          void deps.safely(finishRun, 'The finished Build task could not be refreshed.');
        }
      };
      source.onerror = () => {
        if (deps.state.source === source && deps.state.actionLine && !deps.state.actionLine.ended) {
          const action = deps.state.actionLine;
          if (!action.beforeDisconnect) action.beforeDisconnect = { words: action.words, at: action.at };
          deps.state.actionLine.words = 'Reconnecting';
          deps.state.actionLine.at = Date.now();
          window.ThomasCodeLiveView?.paintExtras?.(deps.state);
        }
        void handleStreamError(source);
      };
    }


    async function handleStreamError(source) {
      if (deps.state.source !== source || !deps.state.running) return false;
      const runId = deps.state.runId;
      const epoch = deps.state.contextEpoch;
      deps.state.source = null;
      source.close();
      let status;
      try {
        const response = await fetch(`/api/evolve/agent/status?run_id=${encodeURIComponent(runId)}`);
        status = await response.json();
        const missingRun = response.status === 404 && status.code === 'run_not_found';
        if (!missingRun && (!response.ok || !status.ok)) throw new Error(status.error || 'Build status check failed.');
      } catch (error) {
        if (deps.state.source || deps.state.runId !== runId || deps.state.contextEpoch !== epoch) return false;
        deps.state.runStatus = 'disconnected';
        deps.pushLiveEvent({ type: 'error', text: `${deps.errorText(error, 'Build status could not be verified.')} Live updates dropped. Reconnecting; the task is still marked running.` });
        deps.render();
        openStream();
        return false;
      }
      if (deps.state.source || deps.state.runId !== runId || deps.state.contextEpoch !== epoch || (status.run_id && status.run_id !== runId)) return false;
      deps.controls?.applyControls?.(status);
      if (status.running === true || status.recording === true) {
        deps.state.runStatus = status.running === true ? 'working' : 'stopping';
        const text = status.running === true
          ? 'Live updates were interrupted, but Thomas is still running. Reconnecting without releasing the task.'
          : 'The process stopped and Thomas is still recording the result. Reconnecting until the durable result is ready.';
        deps.pushLiveEvent({ type: 'disconnected', text });
        deps.render();
        openStream();
        return true;
      }
      if (deps.state.steeringBusy) {
        finishBusy();
        return true;
      }
      deps.state.runStatus = 'disconnected';
      deps.pushLiveEvent({ type: 'disconnected', text: 'The stream ended and the backend reports no active or recording Build task.' });
      window.ThomasCodeLiveView?.finishAction?.(deps.state, { ok: false }, false);
      deps.updateRunStatus();
      await finishRun();
      return true;
    }


    function finishBusy() {
      deps.state.running = false;
      deps.host().setBusy && deps.host().setBusy(false);
      deps.codeProjects().updateProjectButton();
      // The history reload ran while the run still counted as live, so the row kept "Step 4 of 4";
      // re-mark it now that it reads as finished (Verified / Stopped / Needs attention).
      deps.host().renderHistory && deps.host().renderHistory();
    }


    async function finishRun() {
      if (deps.state.finishing) return deps.state.finishing;
      const runId = deps.state.runId;
      // Set by the durable branch below, read after the final render: the scroll
      // has to run against the DOM that render() just painted, and only when this
      // run's own result landed (a superseded finisher must not yank the view).
      let landedDurably = false;
      deps.state.finishing = (async () => {
        const id = deps.state.activeId;
        const epoch = deps.state.contextEpoch;
        const proof = deps.state.runProof ? { ...deps.state.runProof } : null;
        const results = await Promise.allSettled([id ? deps.loadConversation(id, { internal: true, epoch, deferRender: true }) : Promise.resolve(false), deps.refresh({ throwOnError: true })]);
        const sameRun = deps.state.contextEpoch === epoch && deps.state.runId === runId;
        const durable = results[0].status === 'fulfilled' && results[0].value === true && sameRun && deps.lifecycle().runIsDurable(deps.state.conversation, proof);
        if (durable) {
          landedDurably = true;
          deps.state.liveEvents = [];
          deps.state.artifacts = [];
          deps.state.runProof = null;
          // Put the thing Thomas just made in front of the person who asked for
          // it. Finishing a build and leaving the result to be discovered is how
          // "where is it" and "what's the full directory name" became the two
          // messages after a successful game build.
          void deps.codeResults().presentNewestResult();
        } else if (sameRun && results[0].status === 'fulfilled' && results[0].value === true) {
          deps.state.runStatus = 'disconnected';
          deps.pushLiveEvent({ type: 'error', text: 'Thomas stopped, but the just-finished Build turn is not yet present in durable history. Live evidence was preserved.' });
        }
        results.filter(result => result.status === 'rejected').forEach(result => deps.pushLiveEvent({ type: 'error', text: deps.errorText(result.reason, 'The Build result could not be refreshed.') }));
      })();
      try { await deps.state.finishing; } finally {
        const sameRun = deps.state.runId === runId;
        deps.state.finishing = null;
        if (sameRun) {
          finishBusy();
          deps.render();
          // A run that ends on a tab you are not looking at says so on the tab you are (attention_cards.js
          // shows nothing when this tab is the one on screen).
          if (window.ThomasAttention && window.ThomasAttention.taskEnded) {
            window.ThomasAttention.taskEnded({ id: deps.state.activeId, title: (deps.state.conversation || {}).title, status: deps.state.runStatus });
          }
          // A follow-up run's answer appends BELOW the turn the reader is parked
          // at, and scrollTranscriptToNewest only ran on conversation OPEN -- so
          // the durable result of a run watched in an open conversation landed
          // below the fold, invisible until a manual scroll. The loadConversation
          // above is `internal`, which deliberately never scrolls (it also runs
          // under live reloads where yanking the view would fight a reader); the
          // moment a run's own durable result lands is the one internal reload
          // where arriving at the newest turn is the point.
          if (landedDurably) deps.scrollTranscriptToNewest();
        }
      }
      // Codex-parity task queue: a message sent while a run was going starts
      // automatically the moment this run's result is durable.
      startNextQueued();
    }

    // The stop-and-continue steer, for a run whose lead cannot take messages
    // (the Claude Code lead): stop this attempt and continue the same task with
    // your words. The queue's Steer (unified_code_controls.js) falls back to it.
    async function steer(message) {
      const text = String(message || '').trim(); if (!text || !deps.state.running || deps.state.steeringBusy) return false;
      deps.state.steeringBusy = true;
      const steeringConversation = deps.state.activeId;
      const steeringRun = deps.state.runId;
      const steeringEpoch = deps.state.contextEpoch;
      deps.render();
      try {
        const response = await fetch('/api/evolve/agent/steer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text, run_id: steeringRun }) });
        const data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || 'Steering failed.');
        deps.pushLiveEvent({ type: 'steering', text: `Applying your update to this task: ${text}` });
        deps.state.runStatus = 'stopping';
        deps.render();
        await deps.waitForRestartReady(steeringRun);
        if (deps.state.activeId !== steeringConversation || deps.state.runId !== steeringRun || deps.state.contextEpoch !== steeringEpoch) return false;
        closeSource();
        deps.pushLiveEvent({ type: 'steering', text: 'Previous attempt stopped. Continuing this task with your update…' });
        finishBusy();
        const continued = await deps.send(`Steering update: ${text}`, deps.state.lastContext, { preserveProgress: true });
        if (continued) deps.pushLiveEvent({ type: 'steering', text: 'Update applied to this task.' });
        else deps.pushLiveEvent({ type: 'error', text: 'Your update was not applied. The previous attempt stopped; review the error and retry in this task.' });
        return continued;
      } catch (error) {
        deps.pushLiveEvent({ type: 'error', text: `Your update was not applied: ${error.message || 'continuation failed'}. Retry in this task.` });
        throw error;
      } finally {
        deps.state.steeringBusy = false;
        deps.render();
      }
    }

    function startNextQueued() {
      if (!deps.state.queuedSends || !deps.state.queuedSends.length) return;
      // Never drain while something is live: send() would re-queue the entry,
      // and a drain-then-requeue is where a cid can be rewritten to whatever
      // conversation happens to be active at that moment.
      if (deps.state.running || deps.state.finishing) return;
      // Drain ONLY tasks queued for exactly the ACTIVE conversation; tasks for a
      // parked conversation wait until the user returns to it (misdelivery
      // guard). `entry.cid` must match, never merely be absent: the absent-cid
      // shortcut is what fired the countdown task into the live Bitcoin
      // conversation and overwrote its deliverable (w2-code-tiny, 2026-08-05).
      // A message being steered into the run is not a task to start.
      const held = entry => Boolean(window.ThomasCodeControls?.held?.(deps.state, entry));
      const index = deps.state.queuedSends.findIndex(entry => Boolean(entry.cid) && entry.cid === deps.state.activeId && !held(entry));
      if (index >= 0) {
        const queued = deps.state.queuedSends.splice(index, 1)[0];
        deps.pushLiveEvent({ type: 'planning', text: `Starting your queued task: ${queued.message.slice(0, 80)}` });
        deps.render();
        void deps.safely(() => deps.send(queued.message, queued.context), 'The queued Build task failed to start.');
        return;
      }
      // An entry with no conversation stamp can no longer be created (see the
      // queue branch in send), but one that somehow exists must become its own
      // NEW conversation -- adopting whichever conversation is on screen is
      // exactly the overwrite this queue shipped once already.
      const orphanIndex = deps.state.queuedSends.findIndex(entry => !entry.cid);
      if (orphanIndex < 0) return;
      const orphan = deps.state.queuedSends.splice(orphanIndex, 1)[0];
      deps.state.contextEpoch += 1;
      deps.clearContextState();
      deps.pushLiveEvent({ type: 'planning', text: `Starting your queued task as its own conversation: ${orphan.message.slice(0, 80)}` });
      deps.render();
      void deps.safely(() => deps.send(orphan.message, orphan.context), 'The queued Build task failed to start.');
    }
    return { closeSource, acceptStartedRun, openStream, handleStreamError, finishBusy, finishRun, startNextQueued, steer };
  }
  window.ThomasCodeRunStream = { create };
})();
