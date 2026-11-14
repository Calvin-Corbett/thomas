/* Browser-local theme and composer preferences, including the existing migration. */
(function () {
  'use strict';
  // Autonomy defaults to Agent (3): a fresh chat must be able to EXECUTE an
  // ask, not tell the owner to raise a dial and resend. Guardrails stay
  // 'guarded' — dangerous actions still gate on approval. (Calvin, 2026-07-18.)
  const DIAL_DEFAULTS = { autonomy: 3, effort: 'medium', fileAccess: 'workspace', guardrails: 'guarded', memory: true };

  function loadTheme(themes) {
    // Dark or Light only; an older choice resolves to the nearer of the two (workspace_shell.js safeTheme).
    const plain = { dark: 'nebula', aurora: 'nebula', sandstone: 'light' };  // 'nebula' is Dark's stored name
    try { const theme = localStorage.getItem('thomas_chat_theme'); if (theme && themes[theme]) return plain[theme] || theme; }
    catch (_) { /* Storage can be disabled by the browser. */ }
    return 'nebula';
  }

  function loadDials() {
    try {
      const stored = JSON.parse(localStorage.getItem('thomas_dials') || '{}');
      // One-time migration: autonomy 1 stored before 2026-07-18 was the OLD
      // default, not a user choice. Lift it to the new default once; after
      // that the user's own dial changes always stick.
      if (stored.autonomy === 1 && !localStorage.getItem('thomas_dials_autonomy_migrated')) {
        stored.autonomy = DIAL_DEFAULTS.autonomy;
        localStorage.setItem('thomas_dials_autonomy_migrated', '1');
        localStorage.setItem('thomas_dials', JSON.stringify(stored));
      }
      return Object.assign({}, DIAL_DEFAULTS, stored);
    } catch (e) { return Object.assign({}, DIAL_DEFAULTS); }
  }

  function saveDials(dials) {
    try { localStorage.setItem('thomas_dials', JSON.stringify(dials)); } catch (_) {}
  }

  // Option shape: [value, label, description, meta]. The description is shown
  // under the control when that option is selected, because a one-word label
  // cannot carry the difference between "your home folder" and "every drive"
  // — which is what "Full PC" and "Full" meant, sitting next to each other.
  // meta.elevates asks for confirmation; meta.modes limits an option to
  // certain surfaces (there is no "this project" in plain Chat).
  //
  // Token economy is deliberately absent: all three settings resolved to the
  // same 400 passes and identical budgets, and the one function that differed
  // by level has no caller, so it moved a log threshold and nothing else.
  const DIAL_FIELDS = [
    { key: 'autonomy', label: 'Autonomy', num: true, opts: [
      [1, 'Chat only', 'Answers and drafts. Runs no tools.'],
      [2, 'Assist', 'Uses tools when they are clearly needed, and checks in.'],
      [3, 'Agent', 'Picks its own tools and can hand work to a background task.'],
      [4, 'Full autonomy', 'Keeps going without checking in. Best for long jobs you are not watching.', { elevates: true }],
      [5, 'Autopilot', 'Treats a blocker as part of the job: fixes it, then carries on. Money, messages and safety settings still wait for you.', { elevates: true }],
    ] },
    { key: 'effort', label: 'Reasoning effort', opts: [
      ['none', 'None', 'Fastest. No extended thinking.'],
      ['low', 'Low', 'A little thinking before answering.'],
      ['medium', 'Medium', 'The usual balance of speed and care.'],
      ['high', 'High', 'Thinks longer on hard problems.'],
      ['xhigh', 'xHigh', 'Slower still, for genuinely difficult work.'],
      ['max', 'Max', 'Thinks as long as it needs. Slowest and most expensive.'],
    ] },
    { key: 'fileAccess', label: 'Files Thomas can change', opts: [
      ['workspace', "Thomas's own space", 'Only its own scratch folder. Nothing of yours can change.'],
      ['project', 'This project', "Its own space plus the project — including work on Thomas himself. His protected core still asks you first."],
      ['pc', 'Anywhere on my PC', 'Your Desktop, Documents and Downloads too. Windows system files and Thomas’s own code always stay protected.', { elevates: true }],
    ] },
    { key: 'guardrails', label: 'Reaching the internet', opts: [
      ['fortress', 'Off', 'No web, no browser, no remote calls. Local work only.'],
      ['guarded', 'Normal', 'Can read the web. Cannot call out to remote machines.'],
      ['open', 'Open', 'Full web and remote access. In Build mode this is also what unlocks a direct shell.', { elevates: true }],
    ] },
  ];
  // The menus and inputs those controls open -- the AI-settings sheet, the
  // Thomas Library picker, the attachment chips and the mic -- now live in
  // js/chat_composer_panels.js, lifted out when this page passed its
  // 3000-line ceiling. The module is handed the closure values they used to
  // read directly and returns them under the same names, so every call site
  // below is unchanged.

  window.ThomasChatPreferences = { loadTheme, loadDials, saveDials, DIAL_FIELDS };
})();
