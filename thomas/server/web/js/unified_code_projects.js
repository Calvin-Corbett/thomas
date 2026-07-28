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
    rememberProjectName,
    updateProjectButton,
  };
})();
