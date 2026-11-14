(function () {
  'use strict';

  // What Thomas is doing, as a short plain phrase (about four words at most).
  // It is read from the kind of event and the tool's name, never from the
  // event's text: a long message used to land in the status line whole.
  // The phrase, plus the last two parts of the file it is about when the event names one ("reading plugins/build.toml").
  function activityLabel(event) {
    const words = baseLabel(event);
    const file = String(event.path || event.file || event.file_path || '').split(/[\\/]/).filter(Boolean).slice(-2).join('/');
    return words && file && /^Thomas is (reading|editing|searching)$/.test(words) ? `${words} ${file}` : words;
  }

  function baseLabel(event) {
    const kind = String(event.kind || event.type || '').toLowerCase();
    const name = String(event.name || event.tool || event.tool_name || '').toLowerCase();
    if (event.team_progress || name === 'team-progress') return 'Preparing the team';
    if (kind === 'planning') return 'Thomas is planning';
    if (kind === 'steering') return 'Steering';
    if (kind === 'reason' || kind === 'insight' || kind === 'say' || kind === 'final') return 'Thomas is thinking';
    if (kind !== 'tool' && kind !== 'tool_result') return '';
    const text = String(event.text || event.input || '');
    if (name === 'run') return 'Thomas is testing';
    if (/(^|[._-])(edit|write|patch|create|apply_patch)([._-]|$)/.test(name)) return 'Thomas is editing';
    if (/(^|[._-])(read|list|glob)([._-]|$)/.test(name)) return 'Thomas is reading';
    if (/(^|[._-])(grep|search|find)([._-]|$)/.test(name)) return 'Thomas is searching';
    if (/(bash|shell|terminal|exec|command)/.test(name)) {
      return /(?:^|[\s;&|])(?:[\w./\\-]*[\\/])?(?:pytest|py\.test|tox|jest|vitest|mocha|npm\s+(?:run\s+)?test|python(?:\d+(?:\.\d+)?)?\s+-m\s+pytest)(?:\s|$)/i.test(text)
        ? 'Thomas is testing' : 'Thomas is running';
    }
    return '';
  }

  // The status line directly above the composer (design 3a): a short phrase for
  // what Thomas is doing, then "Step 4 of 5 · 1m 12s" -- the plan's step and
  // how long the run has been going -- or, once it ended, when it ended.
  function statusOf(state) {
    const action = state.actionLine;
    if (!action || action.ended || (action.conversationId && action.conversationId !== state.activeId)) return null;
    let words = action.words;
    let tone = action.ended ? 'idle' : 'working';
    if (!action.ended) {
      // Your steer is acknowledged the moment you send it, before the lead reads it.
      const unread = (state.steers || []).some(steer => steer.runId === state.runId && ['sending', 'queued', 'restarting'].includes(steer.state));
      if (unread) words = 'Acknowledging your message';
    }
    if (!action.ended && state.running && state.paused) {
      words = state.pauseHeld ? 'Paused' : 'Pausing…';
      if (state.pauseHeld) tone = 'paused';
    }
    const plan = !action.ended && state.plan && window.ThomasCodeCards ? window.ThomasCodeCards.planProgress(state.plan) : null;
    const elapsed = state.runStartedAt ? Math.max(0, Date.now() - state.runStartedAt) : '';
    // The plan's step count lives in the Steps card; only the clock stays here.
    return { words, tone, stepText: '', elapsed };
  }

  // Messages you sent while Thomas worked, for the conversation on screen. One
  // already in the live lead's inbox shows as its steer chip instead.
  function queuedFor(state) {
    const inInbox = window.ThomasCodeControls?.inInbox || (() => false);
    return (state.queuedSends || []).filter(entry => entry && entry.cid && entry.cid === state.activeId && !inInbox(state, entry))
      .map(entry => ({ id: entry.id, message: entry.message, busy: Boolean(state.steeringQueueId) && String(state.steeringQueueId) === String(entry.id) }));
  }

  // The stack above the composer (#tc-code-composer-extras): the queue, then
  // the status line. ThomasCodeComposer patches only what changed, so this is
  // cheap enough to call on every event and every second. Outside Build the
  // stack is emptied, which hides it.
  function paintExtras(state) {
    const view = window.ThomasCodeLiveView;
    const composer = window.ThomasCodeComposer;
    const mount = typeof document !== 'undefined' && document.getElementById ? document.getElementById('tc-code-composer-extras') : null;
    if (!composer || !view.activeEsc || !mount || typeof mount.querySelector !== 'function') return;
    const active = !view.activeIsActive || view.activeIsActive();
    composer.render(mount, active
      ? { esc: view.activeEsc, queued: queuedFor(state), status: statusOf(state), steerDisabled: Boolean(state.steeringBusy) }
      : { esc: view.activeEsc, queued: [], status: null });
  }

  if (typeof window.setInterval === 'function') window.setInterval(() => {
    const state = window.ThomasCodeLiveView?.activeState;
    if (state?.actionLine && !state.actionLine.ended) paintExtras(state);
  }, 1000);

  function finishAction(state, done, stopped) {
    const action = state.actionLine;
    if (!action) return;
    const count = Array.isArray(done.changed_files) ? done.changed_files.length : Number(done.changed_files) || 0;
    action.words = stopped || done.outcome === 'stopped' ? 'Thomas stopped'
      : done.ok !== true || done.persistence_confirmed !== true ? 'Ended with a problem'
      : done.noop || !count ? 'Finished, no changes'
      : `Finished, ${count} ${count === 1 ? 'file' : 'files'} changed`;
    action.at = Date.now();
    action.ended = true;
    paintExtras(state);
  }

  const HEARTBEAT_MS = 45000;

  function create({
    state, surface, isActive, render, loadFile, esc, MAX_LIVE_EVENTS, MAX_VISIBLE_PROGRESS_EVENTS, annotateTerminalEvent, flagExpectedProbe, eventType, eventHtml, isTechnicalEvent, progressEvents, finalReplyEvent, interleavedActivityHtml
  }) {
    window.ThomasCodeLiveView.activeState = state;
    window.ThomasCodeLiveView.activeSurface = surface;
    window.ThomasCodeLiveView.activeEsc = esc;
    window.ThomasCodeLiveView.activeIsActive = isActive;
    const hiddenEvents = new WeakSet();  // frames pushLiveEvent left out of the feed
    function observeAction(event) {
      if (!state.actionLine || !state.running) return;
      const words = activityLabel(event);
      if (words) {
        if (words === state.actionLine.words) return;
        state.actionLine.words = words;
        state.actionLine.at = Date.now();
        paintExtras(state);
      }
    }

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

    function updateRunStatus() {
      if (!isActive()) return;
      const badge = surface()?.querySelector('.tc-mode-status'); if (!badge) return;
      const labels = { ready: 'Ready', blocked: 'Check Tools', working: 'Working', stopping: 'Stopping', approval: 'Approval required', completed: 'Completed', noop: 'No changes made', stopped: 'Stopped', disconnected: 'Disconnected', failed: 'Needs attention' };
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
      // Same probe flag the durable transcript parse applies, so the live row and
      // the reloaded row agree. "Has a tool_result come before this one" is read
      // off the live ring; if the run's first tool_result has already scrolled out
      // of the 120-event ring, a later one could in principle be misread as the
      // first -- but by then hundreds of events have passed and the durable
      // render, which parses the whole transcript, is the record that lasts.
      flagExpectedProbe(event, state.liveEvents.some(item => eventType(item) === 'tool_result'));
      observeAction(event);
      if (state.running) refreshOpenPagePreview();
      // A helper's work is the Activity drawer's (fed by the run's controls),
      // and the team's tally has its own line: neither takes a place in the
      // feed's ring, where a busy team would push Thomas's own lines out.
      if (window.ThomasCodeAgentRows?.hiddenLive(event, state.liveEvents)) { hiddenEvents.add(event); return false; }
      const previous = state.liveEvents[state.liveEvents.length - 1];
      if (event.kind === 'say' && event.delta && previous && previous.kind === 'say' && previous.delta
          && ['agent_id', 'agent_title', 'agent_mode', 'model', 'team_id'].every(key => event[key] === previous[key])) {
        previous.text = `${previous.text || ''}${event.text || ''}`;
        return true;
      }
      state.liveEvents.push(event);
      while (state.liveEvents.length > MAX_LIVE_EVENTS) state.liveEvents.shift();
      return false;
    }

    function trimLiveEventDom(list) {
      // Trim ONLY against the ring bound. This used to trim down to the count of
      // narrative events, which was written for the old feed where the list held
      // narrative rows only — with receipts streaming inline it deleted the run's
      // history off the top while the reader watched (owner: "I can't see stuff
      // 7 messages ago").
      while (list.children.length > MAX_LIVE_EVENTS) list.firstElementChild.remove();
    }

    // "Still working": a run that has put nothing new in the feed for 45 seconds
    // says so once, with the step it is on. One line, replaced (never stacked),
    // and gone the moment a real row arrives.
    let lastRowAt = Date.now();
    function markRow() {
      lastRowAt = Date.now();
      surface()?.querySelectorAll('[data-code-heartbeat]').forEach(node => node.remove());
    }
    function heartbeat() {
      const live = state.running && !state.paused && state.actionLine && !state.actionLine.ended;
      if (!live) { lastRowAt = Date.now(); return; }
      if (Date.now() - lastRowAt < HEARTBEAT_MS) return;
      const list = surface()?.querySelector('#tc-code-live-events');
      if (!list) return;
      lastRowAt = Date.now();
      const plan = state.plan && window.ThomasCodeCards ? window.ThomasCodeCards.planProgress(state.plan) : null;
      const step = plan && plan.items ? plan.items.find(item => item.status === 'in_progress') : null;
      const what = step ? String(step.text || '').trim().replace(/[.!?]+$/, '') : String((state.actionLine && state.actionLine.words) || 'Thomas is on it').replace(/^Thomas is /, '');
      list.querySelectorAll('[data-code-heartbeat]').forEach(node => node.remove());
      list.insertAdjacentHTML('beforeend', `<div class="tc-code-stepnote" data-code-kind="stepnote" data-code-heartbeat="true">Still working: ${esc(what)}</div>`);
      const transcript = transcriptScroller(surface());
      if (transcript && transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 120) transcript.scrollTop = transcript.scrollHeight;
    }
    if (typeof window.setInterval === 'function') window.setInterval(heartbeat, 5000);

    // The line at the very bottom of the feed: the newest step ("Read package.json", "Ran diff…"), replaced by the
    // next as it happens. It sits after the live list, so it stays the last thing in the chat as the chat grows, and
    // it brings the view down with it only when you were already at the bottom.
    function paintDoing() {
      const root = surface();
      const list = root && root.querySelector('#tc-code-live-events');
      if (!list || !list.parentElement) return;
      let line = list.parentElement.querySelector(':scope > [data-code-doing]');
      const live = state.running && !state.paused && state.actionLine && !state.actionLine.ended;
      const rows = list.querySelectorAll('.tc-code-receipts > *');
      const last = rows.length ? rows[rows.length - 1] : null;
      // A step is a <details>: its summary is the one-line face ("Read package.json"); its body is the whole output.
      const face = last && last.querySelector ? last.querySelector('summary') : null;
      const part = selector => (face && face.querySelector(selector) ? face.querySelector(selector).textContent : '');
      const said = face ? `${part('.tc-code-work-verb')} ${part('.tc-code-work-detail')}` : (last ? last.textContent : '');
      const text = said.replace(/\s+/g, ' ').trim().slice(0, 140);
      if (!live || !text) { if (line) line.remove(); return; }
      const transcript = transcriptScroller(root);
      const nearBottom = !transcript || transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 80;
      if (!line) {
        line = document.createElement('div');
        line.className = 'tc-code-doing';
        line.setAttribute('data-code-doing', '');
      }
      if (line.textContent !== text) line.textContent = text;
      if (list.nextElementSibling !== line) list.insertAdjacentElement('afterend', line);
      if (nearBottom && transcript) transcript.scrollTop = transcript.scrollHeight;
    }
    if (typeof window.setInterval === 'function') window.setInterval(paintDoing, 1000);

    function appendLiveEvent(event, replaceLast) {
      if (hiddenEvents.has(event)) return;
      const list = surface()?.querySelector('#tc-code-live-events'); if (!list) { render(); return; }
      const transcript = transcriptScroller(surface());
      const nearBottom = !transcript || transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 80;
      const kind = eventType(event);
      if (kind === 'final') {
        render();
        return;
      }
      // A plan draws nothing inline: the STEPS card above the feed shows it. A
      // question and its answer live in the turn's own slot ([data-code-live-ask],
      // drawn by the run's controls), so a busy feed can never scroll it away.
      if (kind === 'plan') {
        // ...but a step finishing or starting is an update line: said once, here,
        // from the change against the plan before this one.
        const cards = window.ThomasCodeCards;
        const at = state.liveEvents.lastIndexOf(event);
        const earlier = at > 0 ? state.liveEvents.slice(0, at).filter(item => eventType(item) === 'plan').at(-1) : null;
        const notes = cards && at >= 0 ? cards.stepNotes(earlier, event) : [];
        notes.forEach(text => list.insertAdjacentHTML('beforeend', eventHtml({ type: 'stepnote', text, ts: event.ts }, false)));
        if (notes.length) { markRow(); if (nearBottom && transcript) transcript.scrollTop = transcript.scrollHeight; }
        return;
      }
      if (kind === 'ask' || kind === 'answered') return;
      markRow();
      // Every event — narrative AND technical (tool/terminal) — streams inline in
      // arrival order into the single live feed, so the run reads action-by-action
      // in the chat instead of hiding tool work behind a collapsed block.
      const progressCount = state.liveEvents.filter(item => ['insight', 'planning', 'say'].includes(eventType(item))).length;
      if (state.liveEvents.length === MAX_LIVE_EVENTS || progressCount > MAX_VISIBLE_PROGRESS_EVENTS) {
        // Rebuild only the bounded feed. Replacing the whole surface here on
        // every event repeatedly aborted the Outputs iframe's navigation.
        window.ThomasCodeViewState.replaceActivity(surface(), list,
          interleavedActivityHtml(progressEvents(state.liveEvents, finalReplyEvent(state.liveEvents)), false),
          JSON.stringify([state.activeId, state.contextEpoch]), transcript);
        if (nearBottom && transcript) transcript.scrollTop = transcript.scrollHeight;
        return;
      }
      if (replaceLast && list.lastElementChild) {
        // A say-delta can follow tool receipts. Update its own node rather than
        // replacing the latest receipt cluster or the entire surface (which
        // would restart an open preview and steal focus from the steer form).
        // Only patch in place when it is still the last node; otherwise rebuild
        // the feed so a new receipt is not displayed before earlier narration.
        const lastSay = [...list.querySelectorAll('.tc-code-say[data-code-delta="true"]')].at(-1);
        if (lastSay && list.lastElementChild === lastSay) lastSay.outerHTML = eventHtml(state.liveEvents[state.liveEvents.length - 1], false);
        else window.ThomasCodeViewState.replaceActivity(surface(), list,
          interleavedActivityHtml(progressEvents(state.liveEvents, finalReplyEvent(state.liveEvents)), false),
          JSON.stringify([state.activeId, state.contextEpoch]), transcript);
      } else if (isTechnicalEvent(event)) {
        // The incremental path must build the SAME structure the full render
        // builds: receipts live inside a railed cluster under the last thing
        // Thomas said, and the rail breaks when he talks. Without this, every
        // streamed receipt landed bare (no rail) until the next full render
        // rebuilt the thread (owner: "the line on the left isn't there").
        const quiet = window.ThomasCodeCards;
        const before = state.liveEvents.at(-1) === event ? state.liveEvents.at(-2) : null;
        const shown = quiet && before && quiet.pairsWith(before, event) ? quiet.pairToolCalls([before, event])[0] : event;
        if (quiet && quiet.isQuietRow(shown)) return;  // model receipts and look-ups: drawer only
        let cluster = list.lastElementChild;
        if (!cluster || !cluster.classList.contains('tc-code-receipts')) {
          list.insertAdjacentHTML('beforeend', '<div class="tc-code-receipts"></div>');
          cluster = list.lastElementChild;
        }
        // A tool call and its own result are one step: the result replaces the
        // call's row with one that keeps the call's arguments and start time,
        // the same fold the full render makes (ThomasCodeCards.pairsWith).
        const cards = window.ThomasCodeCards;
        const previous = state.liveEvents.at(-1) === event ? state.liveEvents.at(-2) : null;
        if (cards && previous && cards.pairsWith(previous, event) && cluster.lastElementChild) {
          cluster.lastElementChild.outerHTML = eventHtml(cards.pairToolCalls([previous, event])[0], false);
        } else {
          cluster.insertAdjacentHTML('beforeend', eventHtml(event, false));
        }
      } else {
        list.insertAdjacentHTML('beforeend', eventHtml(event, false));
      }
      trimLiveEventDom(list);
      if (nearBottom && transcript) transcript.scrollTop = transcript.scrollHeight;
    }
    return { transcriptScroller, scrollTranscriptToNewest, updateRunStatus, refreshOpenPagePreview, pushLiveEvent, trimLiveEventDom, appendLiveEvent };
  }

  // While a run is live, what Thomas is doing is the one shimmering line at the bottom of the feed; the grey rows of
  // every step stay folded away. A click on that line shows them, and a second click folds them back.
  if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
    document.addEventListener('click', event => {
      const line = event.target && event.target.closest ? event.target.closest('.tc-code-doing') : null;
      if (line) document.documentElement.classList.toggle('tc-show-steps');
    });
  }

  window.ThomasCodeLiveView = { create, paintExtras, statusOf, finishAction };
})();
