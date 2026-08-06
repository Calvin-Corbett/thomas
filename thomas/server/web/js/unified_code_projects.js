// What a Code project folder is CALLED, and the chip that says it.
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
  async function loadProjectNames() {
    let projects;
    try {
      const response = await fetch('/api/local/projects');
      if (!response.ok) return false;
      const data = await response.json();
      projects = Array.isArray(data && data.projects) ? data.projects : null;
    } catch (error) { return false; }
    if (!projects) return false;
    projects.forEach(project => rememberProjectName(project.root_path, project.request_title || project.name));
    updateProjectButton();
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

  function updateProjectButton() {
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

  window.ThomasCodeProjects = {
    configure,
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
  // query, no hash) and the snapshot says a Code conversation was open, write
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
      // A Chat or Work surface must not drag a stale Code conversation along:
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
