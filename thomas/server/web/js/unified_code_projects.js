// What a Build project folder is CALLED, and the chip that says it.
//
// Split out of unified_code_mode.js, which had grown past the 1500-line ceiling
// in thomas/_architecture.py. This is a real seam rather than a line-count
// convenience: naming a folder is the one job here, it touches no run, no
// stream, and no conversation loading, and it is the piece with the longest
// investigation history in the file. Those comments are load-bearing -- two
// earlier passes were REVERTED for guessing at the label, and the notes below
// record what was actually measured in the live UI both times -- so they moved
// here intact with the code they explain.
//
// Loaded before unified_code_mode.js, which calls configure() once with the
// shared state object. These are classic scripts rather than ES modules, so
// injection is how a dependency is named: there is one state, not a copy.
(function () {
  'use strict';

  let state = null;

  function configure(deps) {
    state = deps.state;
    watchSurfaceMoments(state);
  }

  // The moments the surface snapshot must be persisted NOW, not on the next
  // 1s tick. Measured (sweeps/w3-reload-restore): restore-on-reload worked
  // 5/6; the miss reloaded in the window between loadConversation setting
  // state.activeId and the tick writing it, so the snapshot still named the
  // previous surface. There is one shared state object (injected above), so
  // accessor properties on it catch every writer in unified_code_mode.js
  // without that file needing to know persistence exists: opening a
  // conversation (activeId) and starting a run (running) both persist
  // synchronously. The tick and the pagehide flush stay as backstops.
  function watchSurfaceMoments(target) {
    if (!target) return;
    ['activeId', 'running'].forEach(prop => {
      let current = target[prop];
      try {
        Object.defineProperty(target, prop, {
          configurable: true,
          enumerable: true,
          get() { return current; },
          set(value) {
            const changed = value !== current;
            current = value;
            // persistSurface itself skips the write when nothing changed.
            if (changed) persistSurface();
          },
        });
      } catch (_error) { /* frozen state: the 1s tick still covers it */ }
    });
  }

  // The one shared drawer, ~/.thomas/code_scratch. Held here as a path test
  // rather than a basename test because the server's rule is a path rule:
  // `is_shared_scratch` in forge_code_projects.py matches the drawer AND
  // anything beneath it, so a basename check would miss code_scratch/game.
  function isSharedScratchRoot(path) {
    return /[\\/]\.thomas[\\/]code_scratch(?:[\\/]|$)/i.test(String(path || ''));
  }

  // Project names are filed under the folder they name. Windows hands the same
  // folder back as C:\x and c:/x/ depending on who wrote the path, so a raw
  // string key would file one project under two names and answer for neither.
  function projectNameKey(path) {
    return String(path || '').replace(/[\\/]+$/, '').replace(/\\/g, '/').toLowerCase();
  }

  function rememberProjectName(root, name) {
    const key = projectNameKey(root);
    const value = String(name || '').trim();
    if (!key || !value) return;
    state.projectNames[key] = value;
  }

  function knownProjectName(root) {
    const key = projectNameKey(root);
    return key ? (state.projectNames[key] || '') : '';
  }

  // The names shown on the project picker's cards, so the chip and the picker
  // call the same folder the same thing. Without it, a project Thomas built is
  // "exec-25fb7d1499a6" on disk and the chip has nothing better to read: the
  // request that produced it ("Make a small snake game...") lives only in this
  // catalogue. Failure is silent on purpose -- every name here has a folder
  // basename behind it, so an unreachable catalogue costs specificity, not
  // correctness.
  const NAMES_KEY = 'thomas_project_names_v1';
  async function loadProjectNames() {
    // Names seen last time are used at once, so the project chip does not read as a folder name and then change.
    if (!loadProjectNames.primed) {
      loadProjectNames.primed = true;
      try {
        const saved = JSON.parse(localStorage.getItem(NAMES_KEY) || '[]');
        if (Array.isArray(saved) && saved.length) {
          saved.forEach(pair => rememberProjectName(pair[0], pair[1]));
          updateProjectButton();
        }
      } catch (error) { /* an unreadable copy is ignored */ }
    }
    let data;
    try {
      const response = await fetch('/api/local/projects');
      if (!response.ok) return false;
      data = await response.json();
    } catch (error) { return false; }
    if (!Array.isArray(data && data.projects)) return false;
    data.projects.forEach(project => rememberProjectName(project.root_path, project.request_title || project.name));
    try { localStorage.setItem(NAMES_KEY, JSON.stringify(data.projects.slice(0, 300).map(project => [project.root_path, project.request_title || project.name]))); } catch (error) { /* just not remembered */ }
    updateProjectButton();
    if (data.refreshing) setTimeout(loadProjectNames, 800);
    return true;
  }

  function projectDisplayLabel() {
    // A folder basename is a poor name for a thing Thomas built: every app it
    // generates lives in ~/.thomas/workspaces/exec-<hash>, so the chip read
    // "exec-065aad17f4f8". When the picker knows what the project actually is
    // (the request that produced it), that wins.
    //
    // Before that, though: a task with no conversation behind it yet is not
    // going wherever the chip was last pointed. The client keeps the last root
    // in localStorage and sends it along, but the server drops it when it is
    // the shared drawer (`_chosen_project` in evolve_agent_routes.py) and gives
    // the task a folder of its own -- so naming the drawer here names a place
    // the work provably will not go. This mirrors that server rule exactly:
    // same condition (unbound task + shared drawer), same outcome.
    //
    // The guard is checked FIRST because the server drops the drawer no matter
    // what the UI decided to call the place.
    //
    // Two earlier passes hunted this label inside this function and were
    // reverted. Neither cause was here. Clicking 16 sidebar tasks in the live
    // UI and recording the chip after each: 14 of the 16 opens answered HTTP
    // 404, so no load ever happened -- the chip kept describing whatever was
    // open before (twice the unbound phrase above, twelve times some OTHER
    // conversation's project). The 404 was the server resolving a conversation
    // through the project registry while the sidebar had found it by walking
    // the folders; see _load_conversation in evolve_agent_routes.py. The chip
    // was reporting the state honestly the whole time.
    //
    // The second cause was here: a single state.projectLabel, set when a
    // project was picked and never cleared, printed that one name over every
    // conversation opened afterwards. Proven by seeding the stored label with a
    // marker string: two conversations in two different projects both showed
    // the marker while their own tooltips showed their real, differing paths.
    // Names are now filed per folder (knownProjectName), so a name can only
    // ever appear over the folder it belongs to.
    if (!state.activeId && isSharedScratchRoot(state.projectRoot)) return 'A new folder for this task';
    // An OPEN conversation whose folder is the drawer is a different statement:
    // its work is already there, shared with 94 others on this machine. Naming
    // it "code_scratch" says nothing and "A new folder for this task" is a
    // promise about a folder that will never be made. Say where it is.
    if (isSharedScratchRoot(state.projectRoot)) return 'Shared scratch folder';
    const named = knownProjectName(state.projectRoot);
    if (named) return named;
    const base = String(state.projectRoot || '').split(/[\\/]/).filter(Boolean).pop() || '';
    if (!base) return 'Thomas library';
    if (/^exec-[0-9a-f]{6,}$/i.test(base)) return 'Untitled app';
    return base;
  }

  // Build's header: the project chip, then the task's name as plain text. An
  // empty field hides itself (chat.html shows the slot only in Build).
  function updateBuildHeader() {
    const header = document.getElementById('tc-code-header');
    if (!header || typeof header.querySelector !== 'function') return;
    const conversation = state.conversation || {};
    const row = (state.conversations || []).find(item => item.id === state.activeId) || {};
    const fill = (selector, text) => {
      const node = header.querySelector(selector);
      if (node && node.textContent !== text) node.textContent = text;
    };
    fill('[data-code-header-project]', state.projectRoot ? projectDisplayLabel() : '');
    // The same short name the sidebar row shows (its model-named title), not the raw first request.
    const named = state.activeId ? window.ThomasSidebarHistory?.displayTitle?.(state.activeId) : '';
    fill('[data-code-header-title]', state.activeId ? String(named || row.title || conversation.title || '') : '');
  }

  function updateProjectButton() {
    updateBuildHeader();
    const button = document.getElementById('tc-code-project-btn');
    if (!button) return;
    const span = document.getElementById('tc-code-project-label');
    if (span) span.textContent = projectDisplayLabel();
    // The tooltip is the same claim as the label, spelled out as a path, so it
    // cannot be allowed to keep naming the shared drawer after the label has
    // stopped. There is no path to show here yet -- the server picks one when
    // the task starts -- so it goes back to the invitation.
    const unbound = !state.activeId && isSharedScratchRoot(state.projectRoot);
    button.title = (!unbound && state.projectRoot) || 'Choose what Thomas works on';
    button.disabled = state.running || state.approvalBusy || state.steeringBusy;
  }

  // -------------------------------------------------------------------------
  // Starting a task in a folder, leaving one, and coming back to a run that is
  // still going.
  //
  // These moved out of unified_code_mode.js on 2026-08-10, when it stood at
  // 1749 lines against the 1500-line ceiling in thomas/_architecture.py. They
  // came HERE rather than to a new file for a reason this module already
  // demonstrates: every one of them is about WHICH FOLDER and WHICH TASK the
  // surface is pointed at. Creating a task decides its project root (and heals
  // a stale one); the folder picker is the other way in; switching away parks
  // the run and clears the context; reattaching asks whether the run this
  // browser was on is still alive -- and it answers that from the very surface
  // snapshot persisted at the bottom of this file.
  //
  // A factory rather than more configure() state: these need twelve
  // collaborators from unified_code_mode.js (its stream, its renderer, its
  // error reporting), and naming them in one place is what keeps the
  // dependency direction readable. unified_code_mode.js binds the result to
  // local names, so its own call sites are unchanged.
  function createTaskSession(deps) {
    const {
      closeSource, esc, finishBusy, host, lifecycle, loadConversation, loadTree, openStream,
      pushLiveEvent, recordError, recordPreferenceWarning, refresh, render, safely,
    } = deps;
    let recoveredPoll = null;

    function showRecoveredPraxis(status, cid) {
      const recovery = status && status.praxis_recovered;
      if (status?.running === true || !recovery || recovery.lead_attached !== false || !recovery.run_id) return false;
      if (recoveredPoll) clearTimeout(recoveredPoll);
      recoveredPoll = null;
      state.runId = recovery.run_id;
      state.runStatus = 'disconnected';
      state.liveEvents = state.liveEvents.filter(event => event.praxis_recovered !== true);
      pushLiveEvent({ type: 'disconnected', praxis_recovered: true,
        text: 'Thomas restarted during this task. Its helper steps from before the restart are shown below. The main thread stopped, so start a new Build run to continue.' });
      const agents = Array.isArray(recovery.agents) ? recovery.agents : [];
      agents.forEach(agent => pushLiveEvent({
        type: 'agent_status', kind: 'agent_status', praxis_recovered: true,
        agent_id: agent.agent_id, agent_title: agent.title, agent_mode: agent.kind,
        agent_state: agent.state, model: agent.model_used,
        text: agent.state === 'interrupted' ? 'Interrupted on restart; needs a new Build run.' : `Recovered helper · ${agent.attempts || 0} attempt(s)`,
      }));
      render();
      // The lead has stopped, but its recovered read-only children can still
      // change state. Poll only their status; never reopen the lead stream.
      const terminal = new Set(['completed', 'failed', 'stopped', 'cancelled', 'interrupted']);
      if (agents.some(agent => !terminal.has(agent.state))) {
        const poll = async () => {
          if (state.activeId !== cid || state.runId !== recovery.run_id || state.running) return;
          try {
            const response = await fetch(`/api/evolve/agent/status?conversation_id=${encodeURIComponent(cid)}`);
            if (response.ok && showRecoveredPraxis(await response.json(), cid)) return;
          } catch (_) { /* A transient status failure can clear on the next poll. */ }
          recoveredPoll = setTimeout(poll, 2000);
        };
        recoveredPoll = setTimeout(poll, 2000);
      }
      return true;
    }

    // Parallel runs (Codex-style): switching away from a RUNNING conversation
    // parks it — the backend keeps working, and opening that conversation again
    // reattaches via its run_id (same machinery as reload-resume).
    function parkActiveRun() {
      if (!state.running || !state.activeId || !state.runId) return;
      state.parkedRuns = state.parkedRuns || {};
      state.parkedRuns[state.activeId] = { runId: state.runId, startedAt: state.runStartedAt || Date.now() };
      closeSource();
      state.running = false;
      host().setBusy && host().setBusy(false);
    }

    function canSwitchContext() {
      if (!state.approvalBusy && !state.steeringBusy && !state.finishing) {
        // A live run no longer blocks switching — it parks and keeps running.
        if (state.running) {
          if (!state.runId) {
            recordError(null, 'Wait for this Build task to start before switching.');
            return false;
          }
          parkActiveRun();
        }
        return true;
      }
      recordError(null, 'Finish the pending Build approval or steering update before switching.');
      return false;
    }

    function clearContextState() {
      if (recoveredPoll) clearTimeout(recoveredPoll);
      recoveredPoll = null;
      closeSource();
      // Cleared BEFORE finishBusy, which repaints the project chip: leaving the
      // outgoing conversation's id in place made that repaint describe a task
      // that is already gone. At this point nothing is bound, and the chip has to
      // be allowed to say so.
      state.activeId = '';
      state.openingConversationId = '';
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

    // Reattach to THIS conversation's still-running run (parked earlier or found
    // on the server) — the per-conversation half of reload-resume.
    async function reattachRunFor(cid) {
      if (state.running || state.finishing || state.activeId !== cid) return false;
      const token = lifecycle().contextToken(state);
      const parked = (state.parkedRuns || {})[cid];
      let status;
      try {
        const response = await fetch(`/api/evolve/agent/status?conversation_id=${encodeURIComponent(cid)}`);
        status = await response.json();
      } catch (error) { return false; }
      if (!lifecycle().contextMatches(state, token) || state.running || state.finishing) return false;
      if (!status || status.running !== true || !status.run_id) {
        if (parked) delete state.parkedRuns[cid];
        if (showRecoveredPraxis(status, cid)) return true;
        return false;
      }
      lifecycle().adoptRunIdentity(state, status.run_id);
      lifecycle().registerRunProof(state, cid, status.run_id);
      // The stream replays from the start, as a reload does, not from where the
      // park left off: clearContextState emptied the feed, and the run's
      // controls start over for it -- a `paused` or `ask` frame from before the
      // park is the only record that the run is held, or waiting on you.
      state.eventCursor = 0;
      if (parked) delete state.parkedRuns[cid];
      state.running = true;
      state.runStatus = 'working';
      const startedRaw = (status.session || {}).started_at;
      state.runStartedAt = (parked && parked.startedAt) || (Number(startedRaw) ? Number(startedRaw) * 1000 : Date.parse(String(startedRaw || ''))) || Date.now();
      host().setBusy && host().setBusy(true);
      pushLiveEvent({ type: 'reconnected', text: 'Reconnected. This task kept running in the background.' });
      render();
      openStream();
      return true;
    }

    async function newConversation(projectRoot, projectLabel, options) {
      if (!canSwitchContext()) return false;
      const epoch = state.contextEpoch + 1;
      state.contextEpoch = epoch;
      // The task on screen goes at once; the new one's page is drawn the moment the server answers.
      state.openingConversationId = '__new__';
      render();
      const context = host().getContext ? host().getContext() : {};
      const historyChoice = String((options && options.historyChoice) || '').trim();
      const newProjectName = String((options && options.newProjectName) || '').trim();
      const selfEdit = options?.selfEdit === true;
      // Inherit only a root somebody PICKED, never the folder of whatever
      // conversation happened to be on screen. state.projectRoot follows every
      // open, so inheriting it bound each new task into the previous task's
      // folder -- measured 2026-08-05: task B built inside task A, and A's run
      // report listed B's page as its own output.
      const explicitPick = projectRoot != null || Boolean(newProjectName);
      const requestedRoot = String(projectRoot == null ? state.chosenProjectRoot : projectRoot).trim();
      // `picked` tells the server this root is a real choice. A root restored
      // from localStorage travels WITHOUT it, so a leftover task folder saved by
      // an older session is declined server-side and the task gets its own.
      const pickFlag = requestedRoot && (explicitPick || state.chosenProjectPicked) ? 'picked' : undefined;
      const response = await fetch('/api/evolve/agent/conversations/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_root: requestedRoot || undefined, project_choice: pickFlag, history_choice: historyChoice || undefined, new_project_name: newProjectName || undefined, self_edit: selfEdit, project_identity: selfEdit ? 'thomas-source' : undefined, self_edit_scope: selfEdit ? options.selfEditScope : undefined, ...lifecycle().requestSettings(context) }) }).catch(error => { if (epoch === state.contextEpoch) { state.openingConversationId = ''; render(); } throw error; });
      const data = await response.json().catch(error => { if (epoch === state.contextEpoch) { state.openingConversationId = ''; render(); } throw error; });
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
        if (epoch === state.contextEpoch) state.openingConversationId = '';
        render();
        return false;
      }
      if (!response.ok || !data.ok) { if (epoch === state.contextEpoch) { state.openingConversationId = ''; render(); } }
      if (!response.ok || !data.ok) throw new Error(data.error || 'Could not create Build task.');
      state.pendingHistoryChoice = null;
      if (epoch !== state.contextEpoch) return false;
      clearContextState();
      state.activeId = data.conversation.id;
      state.conversation = data.conversation;
      state.projectRoot = data.conversation.project_root || requestedRoot;
      rememberProjectName(state.projectRoot, projectLabel);
      updateProjectButton();
      if (explicitPick && !selfEdit) {
        // Only a real pick becomes the sticky default for future tasks -- and
        // only real picks reach localStorage, so a task-born folder can no
        // longer install itself as every later session's destination.
        state.chosenProjectRoot = state.projectRoot;
        state.chosenProjectPicked = true;
        try {
          localStorage.setItem('thomas_code_project_root', state.chosenProjectRoot);
          localStorage.setItem('thomas_code_project_label', knownProjectName(state.chosenProjectRoot));
        } catch (error) { recordError(error, 'Project selection could not be saved for the next session.'); }
      } else if (requestedRoot && projectNameKey(state.projectRoot) !== projectNameKey(requestedRoot)) {
        // The server declined the restored root (a leftover task folder from an
        // older session). Stop offering it, or every new task pays the same
        // round-trip to be told the same thing.
        state.chosenProjectRoot = '';
        state.chosenProjectPicked = false;
        try {
          localStorage.removeItem('thomas_code_project_root');
          localStorage.removeItem('thomas_code_project_label');
        } catch (error) { recordPreferenceWarning(error, 'The declined project root could not be cleared.'); }
      }
      const token = lifecycle().contextToken(state);
      await Promise.all([refresh(), loadTree('', { token, deferRender: true })]);
      render();
      return true;
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

    // Reload-resume (Codex parity): a Build run in progress must survive a page
    // reload — on entering Code mode, reattach to the backend's running run
    // instead of showing a dead surface while the agent keeps working.
    async function adoptOrphanRun() {
      if (state.running || state.finishing) return false;
      const token = lifecycle().contextToken(state);
      let status;
      try {
        const response = await fetch('/api/evolve/agent/status');
        status = await response.json();
      } catch (error) { return false; }
      if (!lifecycle().contextMatches(state, token) || state.running || state.finishing) return false;
      if (!status || status.running !== true || !status.run_id) return false;
      const session = status.session && typeof status.session === 'object' ? status.session : {};
      const cid = String(session.conversation_id || '');
      // Adopt ONLY a run this browser was actually on. Blanket adoption turned
      // every fresh session into an attachment to whatever run happened to be
      // live -- and a new task typed into that "fresh" composer then queued into
      // the adopted conversation, ran in its project, and overwrote its
      // deliverable (measured twice, 2026-08-05/06: a countdown ask replaced a
      // finished Bitcoin dashboard; wave-3 isolation reproduced it from a clean
      // profile). The stored last-surface snapshot is the evidence of "was on
      // it": a same-browser reload carries it and reattaches exactly as before;
      // a genuinely fresh session carries nothing and stays fresh -- the live
      // run remains visible in the sidebar and status, one click away.
      //
      // That snapshot is written by persistSurface() below, which is why this
      // reader lives in the same file as its writer.
      if (cid) {
        let wasHere = false;
        try {
          const stored = JSON.parse(localStorage.getItem(SURFACE_STORE_KEY) || 'null');
          wasHere = Boolean(stored && String(stored.codeConversationId || '') === cid);
        } catch (error) { wasHere = false; }
        // The snapshot is shared by every tab, so it proves only that SOME tab was on this run. A Build tab the
        // browser shell opened with no conversation of its own (tab_mode=code without forge_code) is a new build by
        // construction -- the shell reopens a tab's own conversation itself -- and adopting here made every New build
        // pressed during a run open one more tab showing that same run.
        const address = String(window.location?.search || '');
        if (/[?&]tab_mode=code(&|$)/.test(address) && !/[?&]forge_code=/.test(address)) wasHere = false;
        if (!wasHere && state.activeId !== cid) return false;
      }
      if (cid && state.activeId !== cid) {
        // Loading owns its selection epoch and reattaches its own run. A late
        // global status response must neither steal a newer selection nor open
        // a second stream after that conversation has already reconnected.
        const opening = loadConversation(cid);
        const epoch = state.contextEpoch;
        const loaded = await opening;
        return !!loaded && state.contextEpoch === epoch && state.activeId === cid && state.running;
      }
      lifecycle().adoptRunIdentity(state, status.run_id);
      state.running = true;
      state.runStatus = 'working';
      if (!state.runStartedAt) state.runStartedAt = Date.parse(String(session.started_at || '')) || Date.now();
      host().setBusy && host().setBusy(true);
      pushLiveEvent({ type: 'reconnected', text: 'Reconnected. Thomas kept working through the reload.' });
      render();
      openStream();
      return true;
    }

    // The history question, and the three answers to it.
    //
    // Same shape as the approval prompt in the transcript, because it is the
    // same kind of moment: Thomas needs an answer before it can act, and the
    // answer belongs on screen rather than in a log file. It sits beside
    // newConversation above because it is the other half of that function's
    // 409 branch -- the ask is raised there and answered here, and splitting
    // the pair across two files is what let the ask be raised with no way to
    // answer it for 117 of one user's 121 projects.
    function historyAskHtml() {
      if (!state.pendingHistoryChoice) return '';
      const busy = state.historyChoiceBusy;
      return `<section class="tc-code-approval" role="alert"><strong>${esc(state.pendingHistoryChoice.projectName || 'This folder')} has no version history</strong><p>${esc(state.pendingHistoryChoice.message)}</p><div><button data-code-history-setup ${busy ? 'disabled' : ''}>${busy ? 'Working...' : 'Set up history'}</button><button data-code-history-without ${busy ? 'disabled' : ''}>Work without undo</button><button data-code-history-cancel ${busy ? 'disabled' : ''}>Cancel</button></div></section>`;
    }

    function bindHistoryChoice(root) {
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
    }

    // The project root this browser used last, restored at load.
    function restoreProjectPreference() {
      try {
        // Migration (v2, 2026-07-19): earlier sessions auto-stored the Thomas source
        // repo as the Build project, so every new conversation silently edited the
        // product tree. The v1 migration cleared it once, but a later run re-saved
        // the repo path (scratch resolved into the repo when the server runs from
        // it). v2 re-clears, and we additionally refuse a stored root that looks
        // like the running server's own source checkout. The server also rejects
        // it as a hard safety net.
        if (localStorage.getItem('thomas_code_project_migrated') !== 'v2') {
          localStorage.removeItem('thomas_code_project_root');
          localStorage.setItem('thomas_code_project_migrated', 'v2');
        }
        const storedRoot = localStorage.getItem('thomas_code_project_root') || '';
        // Heuristic client guard: a path ending in the Thomas package folder is the
        // source repo — never use it as a scratch Build project.
        state.projectRoot = /[\\/](thomas|thomas-dev)[\\/]?$/i.test(storedRoot) ? '' : storedRoot;
        if (!state.projectRoot && storedRoot) { try { localStorage.removeItem('thomas_code_project_root'); } catch (e) {} }
        // Restored, not picked: it goes to the server WITHOUT the pick flag, so a
        // leftover task folder saved by an older session heals itself on the next
        // task instead of collecting every build this browser ever starts.
        state.chosenProjectRoot = state.projectRoot;
        state.chosenProjectPicked = false;
        // Restore the human name alongside the path, or a returning user is back to
        // reading "exec-25fb7d1499a6" off the chip. Filed against the PATH it names,
        // never held as "the current label": as a single loose value it outlived the
        // project it belonged to and was then printed over every conversation opened
        // afterwards (measured: the chip read one project's name while its own
        // tooltip showed a different project's path).
        rememberProjectName(state.projectRoot, localStorage.getItem('thomas_code_project_label') || '');
      }
      catch (error) { recordError(error, 'The saved Build project could not be loaded.'); }
    }

    return {
      adoptOrphanRun, bindHistoryChoice, canSwitchContext, clearContextState, historyAskHtml,
      newConversation, pickProject, reattachRunFor, restoreProjectPreference,
    };
  }

  window.ThomasCodeProjects = {
    configure,
    createTaskSession,
    isSharedScratchRoot,
    knownProjectName,
    loadProjectNames,
    projectDisplayLabel,
    projectNameKey,
    rememberProjectName,
    updateProjectButton,
  };

  // -------------------------------------------------------------------------
  // Where the reader LEFT OFF, so F5 does not dump them on the Chat welcome
  // screen. Measured (sweeps/w2-code-stop): reloading during or after a Code
  // task landed on Chat, and the task had to be hunted out of ~197 sidebar
  // rows. Lives in this file rather than a new module because chat.html sits
  // at its line ceiling and cannot take another <script> tag, and this file
  // already holds the one shared state object (configure() above) where the
  // open conversation's id lives.
  //
  // Persist: a snapshot {mode, codeConversationId} in localStorage, refreshed
  // on a 1s tick (written only when it changed) and flushed on pagehide /
  // tab-hide, so the value present at reload is the surface that was on
  // screen when the reload was asked for.
  //
  // Restore: on boot, if the reader arrived with NO explicit destination (no
  // query, no hash) and the snapshot says a Build conversation was open, write
  // `?forge_code=<cid>` into the URL via history.replaceState. That is the
  // exact deep link unified_code_mode.js consumes at DOMContentLoaded — and
  // chat.html loads THIS file first, so this listener runs before that
  // consumer, which then switches to Code, opens the conversation, and strips
  // the parameter, exactly as if the reader had followed the link themselves.
  // Any query or hash already in the URL means the reader chose a landing, so
  // restore stands down: it can never steal an explicit deep link.
  //
  // A stale snapshot self-heals: if the stored conversation no longer opens,
  // unified_code_mode.js reports it once and leaves activeId empty, and the
  // next persistence tick records the surface as it actually is.

  const SURFACE_STORE_KEY = 'thomas.lastSurface';

  function surfaceSnapshot(mode, codeConversationId) {
    const key = String(mode || '').toLowerCase();
    if (key !== 'chat' && key !== 'code' && key !== 'work') return null;
    return {
      mode: key,
      // A Chat or Work surface must not drag a stale Build conversation along:
      // restoring it would move the reader somewhere they had already left.
      codeConversationId: key === 'code' ? String(codeConversationId || '') : '',
    };
  }

  function decideSurfaceRestore(storedRaw, landing) {
    const search = String((landing && landing.search) || '').replace(/^\?/, '');
    const hash = String((landing && landing.hash) || '').replace(/^#/, '');
    if (search || hash) return { restore: false, reason: 'explicit-landing', cid: '' };
    let stored = null;
    try { stored = JSON.parse(String(storedRaw || '')); } catch (_error) { stored = null; }
    if (!stored || typeof stored !== 'object') return { restore: false, reason: 'no-snapshot', cid: '' };
    if (stored.mode !== 'code') return { restore: false, reason: 'default-surface', cid: '' };
    const cid = typeof stored.codeConversationId === 'string' ? stored.codeConversationId : '';
    return { restore: true, reason: cid ? 'code-conversation' : 'code-mode', cid };
  }

  let lastStoredSurface = '';

  function persistSurface() {
    const modesApi = window.ThomasUnifiedModes;
    const mode = modesApi && modesApi.mode ? modesApi.mode() : '';
    const snapshot = surfaceSnapshot(mode, state ? state.activeId : '');
    if (!snapshot) return;
    const raw = JSON.stringify(snapshot);
    if (raw === lastStoredSurface) return;
    try {
      window.localStorage.setItem(SURFACE_STORE_KEY, raw);
      lastStoredSurface = raw;
    } catch (_error) { /* storage denied: restore simply has nothing to read */ }
  }

  function restoreLastSurface() {
    let raw = '';
    try { raw = window.localStorage.getItem(SURFACE_STORE_KEY) || ''; }
    catch (_error) { return; }
    const decision = decideSurfaceRestore(raw, window.location);
    if (!decision.restore) return;
    if (decision.cid) {
      try {
        const url = new URL(window.location.href);
        url.searchParams.set('forge_code', decision.cid);
        window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
      } catch (_error) { /* a URL this page cannot parse is not one to rewrite */ }
      return;
    }
    // Code mode with no open task: nothing for the deep link to open, so ask
    // the modes host directly. DOMContentLoaded guarantees connect() has run
    // (chat.html's inline boot executes during parsing).
    const modesApi = window.ThomasUnifiedModes;
    if (modesApi && modesApi.setMode) void modesApi.setMode('code');
  }

  function bootSurfaceRestore() {
    // A tab document is not the reload target: it neither restores nor records
    // the last surface, or every hidden Build tab would rewrite it each second.
    if (window.parent !== window) return;
    restoreLastSurface();
    // Feature-guarded because sibling node harnesses evaluate this classic
    // script with a minimal window/document; in a real page every guard holds.
    if (typeof window.setInterval === 'function') window.setInterval(persistSurface, 1000);
    if (typeof window.addEventListener === 'function') window.addEventListener('pagehide', persistSurface);
    if (typeof document.addEventListener === 'function') {
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') persistSurface();
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootSurfaceRestore, { once: true });
  } else {
    bootSurfaceRestore();
  }

  window.ThomasCodeSurface = {
    decideSurfaceRestore,
    persistSurface,
    restoreLastSurface,
    surfaceSnapshot,
  };
})();
