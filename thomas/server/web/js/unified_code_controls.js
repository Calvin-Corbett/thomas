/* Build's run controls (window.ThomasCodeControls): pause, resume and stop a
 * run, message its lead or a helper, answer its question (the questions
 * themselves: unified_code_questions.js), hand it a queued message -- the
 * page's half of /api/evolve/agent/{pause,resume,message,messages,answer,
 * live-diff} (evolve_agent_run_control_routes.py) -- and the pieces that read
 * them: the drawer's agents and the side chat, the live turn's head, STEPS card,
 * live diff and steer chips, the Activity button and the sidebar rows.
 * unified_code_mode.js owns the run and its one state object; the fields kept
 * here live on that object, and send, stop, render and the escaper are handed in.
 */
(function () {
  'use strict';

  const POLL_MS = 2000;
  const NO_CONTROLS = { pause: false, message: false, ask: false };
  // A finished task's sub-label and mark in the sidebar, from its newest run.
  const OUTCOME = {
    completed: ['Verified', 'is-done'], conversation: ['Answered', 'is-done'], noop: ['No changes', ''],
    stopped: ['Stopped', ''], failed: ['Needs attention', 'is-failed'],
  };

  // Which finished tasks you have opened, and when: { task id: the task's updated time you last saw }. Kept in this
  // browser only; with storage blocked every finished task simply keeps its tick.
  const SEEN_KEY = 'thomas_code_seen_tasks';
  function readSeen() {
    try { const raw = JSON.parse(localStorage.getItem(SEEN_KEY) || '{}'); return raw && typeof raw === 'object' ? raw : {}; } catch (error) { return {}; }
  }
  function writeSeen(seen) {
    try { localStorage.setItem(SEEN_KEY, JSON.stringify(seen)); } catch (error) { /* the tick just stays */ }
  }

  function create(deps) {
    const { state, esc } = deps;
    Object.assign(state, {
      paused: false, pauseBusy: false, pauseHeld: false, controls: { ...NO_CONTROLS }, steers: [],
      roster: window.ThomasCodeRoster ? window.ThomasCodeRoster.create() : null,
      expandedAgent: null, agentChat: null, agentDraft: '', agentSending: false, agentError: '',
      messages: [], questions: [], liveDiff: null, plan: null, answerBusy: '', steeringQueueId: '',
      queuedSends: state.queuedSends || [], drawerFilesOpen: false, teamProgress: null, agentsEarlierOpen: false,
    });
    let rosterKey = '';        // the run or saved turn the roster was built from
    let observedSeq = 0;       // frames already fed, so a replay is not fed twice
    let controlsFor = '';      // the run whose controls are known
    let chatOwner = '';        // the task and run the side chat and its receipts belong to
    const localReceipts = [];  // side-chat messages still on their way
    let pollAt = 0, polling = false, finalPollFor = '';   // the /messages poll
    let shownKey = '', chatKey = '', lastDrawer = null;  // what the drawer and side chat last drew
    let diffRun = '', holdDiff = false;                   // the live diff's run, and a pause holding its lines

    const isLive = () => Boolean(state.running && state.runId && !state.finishing);
    const surfaceRoot = () => { const root = deps.surface(); return root && typeof root.querySelector === 'function' ? root : null; };
    const cards = () => window.ThomasCodeCards;
    const paintExtras = () => window.ThomasCodeLiveView?.paintExtras?.(state);

    async function postJson(url, body) {
      const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await response.json().catch(() => ({}));
      return { response, data: data && typeof data === 'object' ? data : {} };
    }

    // Thomas's questions and your answers (unified_code_questions.js).
    if (!window.ThomasCodeQuestions) throw new Error('unified_code_questions.js must load before unified_code_controls.js');
    const questions = window.ThomasCodeQuestions.create({
      state, esc, postJson, isLive, isActive: deps.isActive, surfaceRoot, patchSlot: (...args) => patchSlot(...args),
      render: deps.render, pushLiveEvent: deps.pushLiveEvent, recordError: deps.recordError,
    });
    const { openQuestion, answer, answerTyped, syncPlaceholder } = questions;

    // ---------------------------------------------------------------- the run

    function runControls() {
      return { running: isLive(), paused: Boolean(state.paused), canPause: Boolean(state.controls && state.controls.pause) };
    }

    // The primary button with an empty composer: Pause, Resume, or -- for a run
    // that cannot hold, the Claude Code lead -- the one Stop routine.
    async function primaryAction() {
      const composer = window.ThomasCodeComposer;
      const choice = composer ? composer.primaryState({ ...runControls(), hasText: false }) : (isLive() ? 'stop' : 'send');
      if (choice === 'pause') return setPaused(true);
      if (choice === 'resume') return setPaused(false);
      if (choice === 'stop') return stopLive();
      return false;
    }

    // Stop, whatever the primary button offers: Escape in an empty composer, working or paused. False when no run is live.
    function stopLive() {
      if (!isLive()) return false;
      void deps.safely(() => deps.stopRun(), 'Could not stop the Build task.');
      return true;
    }

    // The button, the status line and the Activity button all read paused,
    // pauseBusy and controls; each change re-asks all three.
    function refreshChrome() {
      const host = deps.host();
      if (host && host.setBusy) host.setBusy(Boolean(state.running));
      syncPlaceholder();
      paintExtras();
      repaintAgents(true);
      patchLiveDiff();
      patchStepPill();
    }

    async function setPaused(pause) {
      if (state.pauseBusy || !isLive()) return false;
      const runId = state.runId;
      state.pauseBusy = true;
      refreshChrome();
      try {
        const { response, data } = await postJson(`/api/evolve/agent/${pause ? 'pause' : 'resume'}`, { run_id: runId });
        if (state.runId !== runId) return false;
        if (!response.ok || !data.ok) {
          if (data.code === 'pause_unsupported') state.controls = { ...state.controls, pause: false };
          if (data.code === 'run_not_active') return false;
          throw new Error(data.error || `${pause ? 'Pause' : 'Resume'} failed (${response.status})`);
        }
        // The flag is set the moment this answers; the agents hold at their next
        // step, and the `paused` frame says when they did ("Pausing…" until then).
        state.paused = pause;
        if (!pause) state.pauseHeld = false;
        return true;
      } catch (error) {
        deps.recordError(error, pause ? 'Could not pause the run.' : 'Could not resume the run.');
        return false;
      } finally {
        state.pauseBusy = false;
        syncServices();
        refreshChrome();
      }
    }

    // `controls` (and `paused`) from /send and /status.
    function applyControls(data) {
      if (!data || typeof data !== 'object') return;
      let changed = false;
      if (data.controls && typeof data.controls === 'object') {
        const next = { pause: data.controls.pause === true, message: data.controls.message === true, ask: data.controls.ask === true };
        if (JSON.stringify(next) !== JSON.stringify(state.controls)) { state.controls = next; changed = true; }
        controlsFor = String(data.run_id || state.runId || '');
      }
      if (typeof data.paused === 'boolean' && data.paused !== state.paused && !state.pauseBusy && data.running !== false) {
        state.paused = data.paused;
        if (!data.paused) state.pauseHeld = false;
        changed = true;
      }
      if (changed) refreshChrome();
    }

    // A reattached run (reload, reopened task) never went through /send, so
    // ask /status once what its lead can take.
    function streamOpened() {
      const runId = state.runId;
      if (!runId || controlsFor === runId) return;
      controlsFor = runId;
      void (async () => {
        try {
          const response = await fetch(`/api/evolve/agent/status?run_id=${encodeURIComponent(runId)}`);
          const data = await response.json();
          if (state.runId === runId && data && data.ok) applyControls({ ...data, run_id: runId });
        } catch (error) { /* the controls stay off, which is the safe reading */ }
      })();
    }

    // The side chat, its receipts and the questions belong to one run in one
    // task: another task, or a new run, starts them empty.
    function ownChat(owner) {
      if (owner === chatOwner) return;
      chatOwner = owner;
      localReceipts.length = 0;
      Object.assign(state, { agentChat: null, agentDraft: '', agentError: '', messages: [], questions: [] });
    }

    // A new run on screen: its roster, plan, pause and questions start empty.
    // A run you come back to after parking it is new to this page too: its
    // stream replays from the start (unified_code_projects.js reattachRunFor),
    // so the pause, the open question, the plan and the agents come back.
    function beginLiveRoster() {
      const key = `live:${state.runId}`;
      if (rosterKey === key) return;
      rosterKey = key;
      observedSeq = 0;
      questions.reset();
      ownChat(`${state.activeId}|${state.runId}`);
      if (state.roster) { state.roster.reset(); state.roster.setVerifier(null); state.roster.setReachable([]); }
      Object.assign(state, { plan: null, teamProgress: null, paused: false, pauseHeld: false, messages: [], questions: [], liveDiff: null, contextUse: null, expandedAgent: null });
      state.steers = state.steers.filter(steer => steer.runId === state.runId);
      if (controlsFor !== state.runId) state.controls = { ...NO_CONTROLS };
    }

    // Every SSE frame, before the stream drops tool_started (it carries the
    // file paths and the helpers' briefs the roster needs).
    function observe(frame) {
      if (!frame || typeof frame !== 'object' || !state.runId) return;
      if (frame.run_id && frame.run_id !== state.runId) return;
      beginLiveRoster();
      const seq = Number(frame.event_seq || 0);
      if (seq) { if (seq <= observedSeq) return; observedSeq = seq; }
      if (state.roster) state.roster.feed(frame);
      const kind = String(frame.kind || frame.fc || frame.type || '').toLowerCase();
      if (kind === 'paused') {
        state.paused = true; state.pauseHeld = true;
        syncServices(); refreshChrome();
      } else if (kind === 'resumed') {
        state.paused = false; state.pauseHeld = false;
        syncServices(); refreshChrome();
      } else if (kind === 'plan' && Array.isArray(frame.items)) {
        state.plan = { items: frame.items, ts: Number(frame.ts) || Date.now() };
        patchSteps(); patchStepPill(); paintExtras();
      } else if (window.ThomasCodeAgentRows?.isTeamProgress(frame)) {
        state.teamProgress = frame;  // the team's newest tally, one line in the steps slot
        patchSteps();
      } else if (kind === 'steering' && frame.steer_id) {
        settleSteers(steer => steer.receiptId === frame.steer_id, false);
      } else if ((kind === 'ask' || kind === 'answered') && frame.question_id) {
        if (kind === 'ask') pollAt = 0;
        questions.observe(kind, frame);
      } else if (kind === 'done' || kind === 'stopped') {
        state.paused = false; state.pauseHeld = false;
        // A steer read by the lead wrote its `steering` frame before this one:
        // what is left was never read, and goes back in the queue.
        settleSteers(steer => steer.runId === state.runId && Boolean(steer.entry), true);
        if (kind === 'done' && (state.steers.length || pending())) finalPollFor = state.runId;
      }
    }

    // ------------------------------------------------------------ the roster

    // While a run is live the frames feed the roster; once it has ended, the
    // drawer shows who worked on the newest saved turn (and the Verifier's
    // card on it as one more agent, ThomasCodeRoster.verifierFrom).
    function syncRoster() {
      if (!state.roster) return;
      if (state.running && state.runId) { beginLiveRoster(); return; }
      if (rosterKey.startsWith('live:') && state.liveEvents.length) {
        if (!rosterKey.endsWith(':settled')) {
          state.roster.feed(state.runStatus === 'stopped' ? { kind: 'stopped' } : { kind: 'done', ok: state.runStatus !== 'failed' });
          rosterKey += ':settled';
        }
        return;
      }
      const turns = state.conversation && Array.isArray(state.conversation.turns) ? state.conversation.turns : [];
      const turn = [...turns].reverse().find(item => item && item.role === 'agent') || null;
      const key = `saved:${state.activeId}:${turn ? (turn.run_id || turn.ts || turns.length) : 'none'}`;
      if (key === rosterKey) return;
      rosterKey = key;
      // The run that just settled into this turn keeps its side chat.
      ownChat(`${state.activeId}|${turn ? turn.run_id || '' : ''}`);
      state.roster.reset();
      state.roster.setReachable([]);
      state.roster.setVerifier(null);
      Object.assign(state, { plan: null, teamProgress: null, liveDiff: null, contextUse: null, expandedAgent: null, paused: false, pauseHeld: false });
      if (!turn) return;
      const Roster = window.ThomasCodeRoster;
      Roster.linesOf(deps.transcriptText ? deps.transcriptText(turn) : String(turn.transcript || '')).forEach(line => {
        state.roster.feed(line);
        // The newest plan the run wrote, so the step pill still reads after it ended.
        if (line && (line.kind || line.fc) === 'plan' && Array.isArray(line.items)) state.plan = { items: line.items, ts: Number(line.ts) || 0 };
      });
      state.roster.feed(turn.outcome === 'stopped' ? { kind: 'stopped' } : { kind: 'done', ok: turn.ok !== false });
      state.roster.setVerifier(Roster.verifierFrom(turn.report));
    }

    function agentById(id) {
      return state.roster ? state.roster.agents().find(agent => String(agent.id) === String(id)) || null : null;
    }

    function agentFor(file) {
      const claims = state.roster ? state.roster.claims() : [];
      const claim = claims.find(item => item.path === file || item.path.endsWith(`/${file}`));
      return claim ? claim.agentName : '';
    }

    // ------------------------------------------------- polling and the diff

    const liveDiff = window.ThomasCodeLiveDiff ? window.ThomasCodeLiveDiff.create({
      fetchJson: async url => (await fetch(url)).json(),
      onChange: next => {
        if (next === null && holdDiff) return;  // a pause keeps the last lines on screen
        state.liveDiff = next;
        patchLiveDiff();
      },
      agentFor,
    }) : null;

    // A side-chat message that failed is not waiting on anything.
    const pending = () => state.steers.some(steer => steer.state === 'queued' || steer.state === 'sending')
      || localReceipts.some(local => local.state !== 'failed') || state.messages.some(message => message.state === 'queued');

    function wantsPoll() {
      if (!state.runId || !deps.isActive()) return false;
      if (isLive()) return pending() || Boolean(state.agentChat) || Boolean(openQuestion());
      return finalPollFor === state.runId;
    }

    async function poll(force) {
      if (polling || !state.runId || (!force && (!wantsPoll() || Date.now() - pollAt < POLL_MS))) return;
      polling = true;
      pollAt = Date.now();
      const runId = state.runId;
      try {
        const response = await fetch(`/api/evolve/agent/messages?run_id=${encodeURIComponent(runId)}`);
        const data = await response.json();
        if (state.runId !== runId || !data || data.ok !== true) return;
        absorbMessages(data);
      } catch (error) { /* a live run's next tick asks again */ } finally {
        polling = false;
        if (!isLive() && finalPollFor === runId) finalPollFor = '';  // the after-the-end read is asked once
      }
    }

    function absorbMessages(data) {
      const before = JSON.stringify([state.messages, state.questions, state.steers.map(steer => steer.state)]);
      state.messages = Array.isArray(data.messages) ? data.messages : [];
      state.questions = Array.isArray(data.questions) ? data.questions : [];
      // How much of the model's context window the lead has used, for the meter beside the Activity button.
      if (data.context && Number(data.context.window) > 0) {
        state.contextUse = { tokens: Number(data.context.tokens) || 0, window: Number(data.context.window), breakdown: Array.isArray(data.context.breakdown) ? data.context.breakdown : [] };
        if (window.ThomasCodeHeader) window.ThomasCodeHeader.paint();
      }
      if (state.roster) state.roster.setReachable(Array.isArray(data.listening) ? data.listening : []);
      state.steers.forEach(steer => {
        const receipt = state.messages.find(message => message.id === steer.receiptId);
        if (receipt) steer.state = receipt.state;
      });
      // An acked steer is drawn by its own `steering` frame where it was read;
      // one the run ended without reading goes back in the queue.
      settleSteers(steer => steer.state === 'acked', false);
      settleSteers(steer => steer.state === 'undelivered', true);
      if (JSON.stringify([state.messages, state.questions, state.steers.map(steer => steer.state)]) !== before) {
        patchSteers();
        syncPlaceholder();
        questions.patch();
      }
      repaintAgents();
    }

    function syncServices() {
      const running = isLive() && deps.isActive();
      if (liveDiff) {
        // Polled only while the live turn has somewhere to show it.
        const root = surfaceRoot();
        if (running && !state.paused && root && root.querySelector('[data-code-live-diff]')) {
          if (diffRun !== state.runId) { liveDiff.start(state.runId); diffRun = state.runId; }
        } else if (diffRun) {
          holdDiff = running && state.paused;
          liveDiff.stop();
          holdDiff = false;
          diffRun = '';
        }
      }
      void poll(false);
    }

    // Once a second, from the mode's clock.
    let rowPreview = '';
    function tick() {
      if (!deps.isActive()) return;
      const root = surfaceRoot();
      if (root && window.ThomasCodeDrawer) window.ThomasCodeDrawer.tick(root);
      syncServices();
      repaintAgents();
      syncPlaceholder();  // a mode switch rewrites the composer's words under an open question
      // The running task's sidebar row ("Step 2 of 5 · 3 agents") follows the run.
      const preview = isLive() ? historyRow({ id: state.activeId }, true).preview : '';
      if (preview !== rowPreview) {
        rowPreview = preview;
        const host = deps.host();
        if (preview && host && host.renderHistory) host.renderHistory();
      }
    }

    // ----------------------------------------------------- messages and steers

    function queued(id) {
      return (state.queuedSends || []).find(entry => String(entry.id) === String(id) && entry.cid === state.activeId) || null;
    }

    function removeQueued(id) {
      const entry = queued(id);
      if (!entry || String(state.steeringQueueId) === String(id)) return;
      state.queuedSends.splice(state.queuedSends.indexOf(entry), 1);
      paintExtras();
    }

    // Steer chips whose message was read (`requeue` false: its queue entry is
    // done with) or never will be (true: the entry is a queued message again,
    // to start after the run the way it would have without the Steer click).
    function settleSteers(match, requeue) {
      const settled = state.steers.filter(match);
      if (!settled.length) return;
      settled.forEach(steer => {
        if (!steer.entry) return;
        if (requeue) delete steer.entry.steeringRun;
        else state.queuedSends = (state.queuedSends || []).filter(item => item !== steer.entry);
      });
      state.steers = state.steers.filter(steer => !settled.includes(steer));
      patchSteers();
      paintExtras();
      // Back in the queue of a task that is no longer running: it starts now.
      if (requeue && !state.running && !state.finishing && deps.startNextQueued) deps.startNextQueued();
    }

    // Steer on a queued message: into the lead's inbox when the lead takes
    // messages (it reads them at its next tool boundary), else the old
    // stop-and-continue steer (unified_code_run_stream.js steer()). Either way
    // the message leaves the queue only once the run has it: until the lead
    // reads it, the entry waits out of sight (`steeringRun`, see held below).
    async function steerQueued(id) {
      const entry = queued(id);
      if (!entry || !isLive() || state.steeringQueueId || state.steeringBusy) return false;
      const runId = state.runId;
      const chip = { id: `steer-${Date.now().toString(36)}`, text: entry.message, state: 'sending', agentId: 'lead', at: Date.now(), runId };
      state.steeringQueueId = String(id);
      state.steers.push(chip);
      patchSteers();
      paintExtras();
      try {
        if (state.controls.message) {
          const { response, data } = await postJson('/api/evolve/agent/message', { run_id: runId, agent_id: 'lead', text: entry.message });
          if (!response.ok || !data.ok || !data.receipt) throw new Error(data.error || `The steer was not delivered (${response.status})`);
          if (!isLive() || state.runId !== runId) throw new Error('the run ended before Thomas could read it');
          Object.assign(chip, { receiptId: data.receipt.id, state: data.receipt.state || 'queued', entry });
          entry.steeringRun = runId;
          pollAt = 0;
          return true;
        }
        chip.state = 'restarting';
        patchSteers();
        const applied = await deps.safely(() => deps.steer(entry.message), 'Could not steer the Build task.');
        state.steers = state.steers.filter(item => item !== chip);
        if (applied) state.queuedSends = state.queuedSends.filter(item => item !== entry);
        return Boolean(applied);
      } catch (error) {
        // The message stays queued, with its own Steer button back.
        state.steers = state.steers.filter(item => item !== chip);
        deps.recordError(error, 'Your steer was not delivered.');
        return false;
      } finally {
        state.steeringQueueId = '';
        patchSteers();
        paintExtras();
      }
    }

    // The side chat's composer: a message straight to one agent's inbox.
    async function messageAgent(text) {
      const target = state.agentChat && state.agentChat.agentId;
      const body = String(text || '').trim();
      if (!target || !body || state.agentSending || !isLive()) return false;
      const local = { id: `local-${Date.now().toString(36)}`, agent_id: target, text: body, state: 'sending', queued_at: Date.now(), acked_at: null };
      localReceipts.push(local);
      Object.assign(state, { agentSending: true, agentError: '', agentDraft: '' });
      patchAgentChat(true);
      try {
        const { response, data } = await postJson('/api/evolve/agent/message', { run_id: state.runId, agent_id: target, text: body });
        if (!response.ok || !data.ok || !data.receipt) throw new Error(data.error || `The message was not delivered (${response.status})`);
        localReceipts.splice(localReceipts.indexOf(local), 1);
        state.messages = state.messages.filter(message => message.id !== data.receipt.id).concat([data.receipt]);
        pollAt = 0;
        return true;
      } catch (error) {
        local.state = 'failed';
        state.agentError = error.message || 'The message was not delivered.';
        return false;
      } finally {
        state.agentSending = false;
        patchAgentChat(true);
      }
    }

    // ------------------------------------------------------------- markup

    function statusWord(label) {
      if (state.running && state.paused) return state.pauseHeld ? 'Paused' : 'Pausing…';
      return label;
    }

    function dotTone() {
      if (state.running) return state.paused && state.pauseHeld ? 'paused' : 'working';
      if (state.runStatus === 'completed' || state.runStatus === 'noop') return 'done';
      if (state.runStatus === 'failed' || state.runStatus === 'disconnected') return 'failed';
      return '';
    }

    // "N agents": while a run is live, the ones still at it (a team of 25
    // that is down to 3 reads "3 agents"); once it ended, everyone who worked.
    function crewCount() {
      const crew = state.roster ? state.roster.agents().filter(agent => agent.id !== 'verifier') : [];
      return state.running ? crew.filter(agent => agent.state === 'working' || agent.state === 'waiting').length : crew.length;
    }

    // The Activity button's contents: icon, label, status, "N agents", dot.
    function activityButtonHtml(label) {
      const crew = crewCount();
      const tone = dotTone();
      return '<svg class="tc-act-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h4l3-7 4 14 3-7h4"/></svg>'
        + '<span class="tc-code-activity-label">Activity</span>'
        + `<small class="tc-code-activity-status">${esc(statusWord(label))}</small>`
        + (crew ? `<small class="tc-code-activity-count">${crew} ${crew === 1 ? 'agent' : 'agents'}</small>` : '')
        + (tone ? `<span class="tc-code-activity-dot" data-tone="${tone}" aria-hidden="true"></span>` : '');
    }

    // Counted inside the hunks only: `---`/`+++` before the first @@ is the
    // file header, and after it `+++count;` is an added `++count;`.
    function diffCounts(diff) {
      if (!diff) return { added: null, removed: null };
      const counts = { added: 0, removed: 0 };
      let inHunk = false;
      String(diff).split('\n').forEach(line => {
        if (line.startsWith('@@')) inHunk = true;
        else if (line.startsWith('diff --git ')) inHunk = false;
        else if (inHunk && line.startsWith('+')) counts.added += 1;
        else if (inHunk && line.startsWith('-')) counts.removed += 1;
      });
      return counts;
    }

    function drawerHtml(ctx) {
      lastDrawer = ctx;
      if (!window.ThomasCodeDrawer) return ctx.extraHtml || '';
      const roster = state.roster;
      return window.ThomasCodeDrawer.html({
        esc, agents: roster ? roster.agents() : [], claims: roster ? roster.claims() : [],
        changes: (ctx.changes || []).map(change => ({ file: change.file, untracked: change.untracked, ...diffCounts(change.diff) })),
        expandedAgent: state.expandedAgent, projectLabel: ctx.projectLabel, running: Boolean(state.running), extraHtml: ctx.extraHtml,
        earlierOpen: Boolean(state.agentsEarlierOpen),
      });
    }

    function chatReceipts() {
      return state.messages.concat(localReceipts);
    }

    function agentChatHtml() {
      const chat = window.ThomasCodeAgentChat;
      const agent = state.agentChat ? agentById(state.agentChat.agentId) : null;
      if (!chat || !agent) return '';
      return chat.html({
        esc, agent, thread: chat.threadFor(agent, chatReceipts()), draft: state.agentDraft,
        sending: state.agentSending, error: state.agentError,
      });
    }

    // The STEPS card, or without a plan the team's newest tally as one quiet line.
    function liveStepsHtml() {
      // With a plan the STEPS card is pinned under the Activity button, not drawn here.
      if (cards() && state.plan && cards().planProgress(state.plan).total) return '';
      const rows = window.ThomasCodeAgentRows;
      return rows && state.teamProgress ? rows.teamHtml(state.teamProgress, esc) : '';
    }

    function liveDiffHtml() {
      if (!cards() || !state.liveDiff) return '';
      return cards().liveDiffHtml({ esc, diff: state.liveDiff, paused: Boolean(state.paused) });
    }

    function steerChipsHtml() {
      if (!cards()) return '';
      return state.steers.filter(steer => steer.runId === state.runId).map(steer => cards().steerChipHtml({ esc, text: steer.text, state: steer.state })).join('');
    }

    // ------------- in-place repaints: between full renders, without rebuilding
    // the transcript or the drawer's file preview (whose iframe would reload).

    function patchSlot(selector, html) {
      const root = surfaceRoot();
      const slot = root && root.querySelector(selector);
      if (slot && slot.innerHTML !== html) slot.innerHTML = html;
    }

    function patchSteps() { patchSlot('[data-code-live-steps]', liveStepsHtml()); }
    function patchLiveDiff() { patchSlot('[data-code-live-diff]', liveDiffHtml()); }
    function patchSteers() { patchSlot('[data-code-live-steers]', steerChipsHtml()); }

    // "Step 2 of 5" under the Activity button: only while the plan has steps.
    function stepPillText() {
      const plan = state.plan && cards() ? cards().planProgress(state.plan) : null;
      return plan && plan.total ? `Step ${Math.max(1, plan.current)} of ${plan.total}` : '';
    }

    // The pinned STEPS card: the whole card, top right under the Activity button
    // (CSS shows it from 1280px wide; narrower, the pill above stands in).
    function stepsPinHtml() {
      return cards() && state.plan ? cards().stepsHtml({ esc, plan: state.plan }) : '';
    }

    function stepPillHtml() {
      const text = stepPillText();
      return `<span class="tc-code-step-pill" data-code-step-pill${text ? '' : ' hidden'}>${esc(text)}</span>`
        + `<div class="tc-code-steps-pin" data-code-steps-pin>${stepsPinHtml()}</div>`;
    }

    function patchStepPill() {
      const root = surfaceRoot();
      const pill = root && root.querySelector('[data-code-step-pill]');
      if (!pill) return;
      const text = stepPillText();
      if (pill.textContent !== text) pill.textContent = text;
      pill.hidden = !text;
      const pin = root.querySelector('[data-code-steps-pin]');
      const html = stepsPinHtml();
      if (pin && pin.innerHTML !== html) pin.innerHTML = html;
    }

    function patchDrawer(root) {
      const box = root.querySelector('.tc-agents-drawer');
      if (!box || !lastDrawer || typeof document === 'undefined' || !document.createElement) return;
      const template = document.createElement('template');
      if (!template.content) return;
      template.innerHTML = drawerHtml(lastDrawer);
      const focused = document.activeElement && box.contains(document.activeElement) ? document.activeElement.id : '';
      ['.tc-agents-head', '.tc-agents-list', '[data-agents-claimed]'].forEach(selector => {
        const now = box.querySelector(selector);
        const next = template.content.querySelector(selector);
        if (now && next && now.outerHTML !== next.outerHTML) now.replaceWith(next);
      });
      bindDrawer(root);
      if (focused) document.getElementById(focused)?.focus({ preventScroll: true });
    }

    // What the side chat shows, minus clocks (a repaint a second rebuilds the box you type in).
    function chatKeyNow() {
      return JSON.stringify([state.agentChat && state.agentChat.agentId, state.roster ? state.roster.snapshotKey() : '',
        chatReceipts(), state.agentSending, state.agentError]);
    }

    function patchAgentChat(force) {
      const root = surfaceRoot();
      if (!root || !deps.isActive()) return;
      const panel = root.querySelector('.tc-code-panel');
      const old = root.querySelector('.tc-code-agent-chat');
      const agent = state.agentChat ? agentById(state.agentChat.agentId) : null;
      const key = chatKeyNow();
      if (!force && key === chatKey && Boolean(old) === Boolean(agent)) return;
      chatKey = key;
      const html = agentChatHtml();
      const focused = document.activeElement && document.activeElement.id === 'tc-agent-chat-input';
      if (old && html) old.outerHTML = html;
      else if (old) old.remove();
      else if (html && panel) panel.insertAdjacentHTML('beforeend', html);
      bindAgentChat(root);
      if (focused) document.getElementById('tc-agent-chat-input')?.focus({ preventScroll: true });
    }

    // The drawer, the Activity button and the side chat, when what they show changed.
    function repaintAgents(force) {
      const root = surfaceRoot();
      if (!root || !deps.isActive() || !root.querySelector('.tc-code-panel')) return;
      const key = JSON.stringify([state.roster ? state.roster.snapshotKey() : '', state.runStatus, state.running, state.paused, state.pauseHeld]);
      if (force || key !== shownKey) {
        shownKey = key;
        const button = root.querySelector('[data-code-results-jump]');
        const status = button && button.querySelector('.tc-code-activity-status');
        if (button && status) button.innerHTML = activityButtonHtml(button.dataset.codeStatusLabel || status.textContent);
        if (state.drawerOpen) patchDrawer(root);
      }
      if (state.agentChat) patchAgentChat(force);
    }

    // ------------------------------------------------------------- binding

    function bindDrawer(root) {
      window.ThomasCodeDrawer?.bind(root, {
        onToggleAgent: id => { state.expandedAgent = String(state.expandedAgent) === String(id) ? null : id; deps.render(); },
        onOpenChat: id => {
          state.agentChat = { agentId: String(id) };
          state.agentDraft = '';
          state.agentError = '';
          state.drawerOpen = false;
          pollAt = 0;
          deps.render();
          void poll(true);
        },
        onToggleEarlier: () => { state.agentsEarlierOpen = !state.agentsEarlierOpen; deps.render(); },
      });
    }

    function bindAgentChat(root) {
      window.ThomasCodeAgentChat?.bind(root, {
        onSend: text => { void messageAgent(text); },
        onClose: () => { state.agentChat = null; state.agentError = ''; deps.render(); },
        onDraft: text => { state.agentDraft = text; },
      });
    }

    // The transcript's own buttons (an ask's options, the proof card's, a
    // deliverable's) are delegated by unified_code_surface.js; an option
    // answers through answer() above.
    function bind(root) {
      if (!root || typeof root.querySelectorAll !== 'function') return;
      bindDrawer(root);
      bindAgentChat(root);
      const composer = window.ThomasCodeComposer;
      const mount = typeof document !== 'undefined' && document.getElementById ? document.getElementById('tc-code-composer-extras') : null;
      if (composer && mount && typeof mount.addEventListener === 'function') {
        composer.bind(mount, { onSteer: id => { void steerQueued(id); }, onRemove: id => removeQueued(id) });
      }
    }

    // After every full render: what the render drew is now what is shown.
    function afterRender(root) {
      bind(root);
      shownKey = JSON.stringify([state.roster ? state.roster.snapshotKey() : '', state.runStatus, state.running, state.paused, state.pauseHeld]);
      chatKey = chatKeyNow();
      syncPlaceholder();
      syncServices();
    }

    // ------------------------------------------------------- the sidebar

    // A Build row's mark and sub-label: "Step 4 of 5 · 3 agents" while it
    // runs, "Verified · 2h ago" (or Stopped / Needs attention) once finished.
    function historyRow(row, active) {
      const history = window.ThomasSidebarHistory;
      if (active && state.running) {
        const crew = crewCount();
        const plan = state.plan && cards() ? cards().planProgress(state.plan) : null;
        const words = [plan && plan.total ? `Step ${Math.max(1, plan.current)} of ${plan.total}` : 'Working',
          crew > 1 ? `${crew} agents` : ''].filter(Boolean).join(' · ');
        return { className: 'is-running', preview: words };
      }
      const outcome = OUTCOME[String(row.last_outcome || '')];
      if (!outcome) return { className: '', preview: '' };
      const stamp = Date.parse(row.updated_at || '') || 0;
      const when = history && stamp ? history.relativeTime(stamp) : '';
      let mark = outcome[1];
      if (mark === 'is-done' && row.id) {
        // A green tick is a notification: it stays until you open the task, then clears. A newer run in the same
        // task brings it back. Red (needs attention) is not cleared by looking: it is still wrong.
        const seen = readSeen();
        if (active) { seen[row.id] = Math.max(Number(seen[row.id]) || 0, stamp); writeSeen(seen); }
        if ((Number(seen[row.id]) || 0) >= stamp && stamp) mark = 'is-seen';
      }
      return { className: mark, preview: [outcome[0], when].filter(Boolean).join(' · ') };
    }

    function leave() {
      if (diffRun && liveDiff) { liveDiff.stop(); diffRun = ''; }
      syncPlaceholder();
      paintExtras();
    }

    return {
      runControls, primaryAction, stopLive, applyControls, streamOpened, observe, tick, syncRoster, answer, answerTyped,
      steerQueued, removeQueued, activityButtonHtml, stepPillHtml, drawerHtml, agentChatHtml,
      liveStepsHtml, liveDiffHtml, steerChipsHtml, liveAskHtml: questions.html, afterRender, historyRow, leave,
    };
  }

  // A queued message waiting in the live lead's inbox: its chip is in the live
  // turn, so the queue does not draw it (unified_code_live_view.js queuedFor).
  // Once that run is not live on screen it is an ordinary queued message again.
  function inInbox(state, entry) {
    return Boolean(entry && entry.steeringRun) && entry.steeringRun === state.runId && Boolean(state.running);
  }

  // ...and, with one whose Steer is in flight, never started after the run
  // (unified_code_run_stream.js startNextQueued).
  function held(state, entry) {
    return Boolean(entry) && ((Boolean(state.steeringQueueId) && String(entry.id) === String(state.steeringQueueId)) || inInbox(state, entry));
  }

  window.ThomasCodeControls = { create, held, inInbox };
})();
