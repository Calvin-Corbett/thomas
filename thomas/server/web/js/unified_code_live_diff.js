/* What an agent is writing right now (window.ThomasCodeLiveDiff).
 *
 * Nothing in a run's event stream carries file contents -- the engines record a
 * path and a one-line summary per edit -- so the live diff block reads the
 * project itself: /api/evolve/agent/live-diff returns the working tree against
 * HEAD, every 3 seconds while a run is live. That tree also holds every change
 * earlier turns left uncommitted, so the first answer is only a baseline: a
 * file shows up once its diff MOVES during this run, never because it was
 * already different when the run began.
 *
 * Polls, parses, and reports; it draws nothing. The caller owns the state the
 * report lands in and renders it through ThomasCodeCards.liveDiffHtml.
 */
(function () {
  'use strict';

  const POLL_MS = 3000;
  const BACKOFF_MS = 15000;
  const MAX_LINES = 12;
  const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

  // The last hunk of a unified diff, as numbered lines: new-file numbers for
  // context and added lines, none for a removed one (it is not in the new file).
  // A hunk longer than MAX_LINES keeps the window that ends just after its last
  // change, which is where the writing is.
  //
  // The `---`/`+++` file header comes before the first `@@`, where `hunk` is
  // still null. Inside a hunk those prefixes are content: `+++count;` adds
  // `++count;`, `----` removes a `---` rule. A new file's header resets.
  function parseLastHunk(diff) {
    const text = String(diff || '').replace(/\r\n/g, '\n');
    let hunk = null;
    text.split('\n').forEach(raw => {
      const header = HUNK.exec(raw);
      if (header) { hunk = { next: Number(header[2]), lines: [] }; return; }
      if (raw.startsWith('diff --git ')) { hunk = null; return; }
      if (!hunk || raw.startsWith('\\')) return;
      const sign = raw.charAt(0);
      if (sign === '+') hunk.lines.push({ n: hunk.next++, sign: '+', text: raw.slice(1) });
      else if (sign === '-') hunk.lines.push({ n: null, sign: '-', text: raw.slice(1) });
      else if (sign === ' ') hunk.lines.push({ n: hunk.next++, sign: ' ', text: raw.slice(1) });
    });
    if (!hunk) return [];
    const lines = hunk.lines;
    // Trailing blank context is the empty string after the diff's final newline.
    while (lines.length && lines[lines.length - 1].sign === ' ' && !lines[lines.length - 1].text) lines.pop();
    let lastChange = -1;
    lines.forEach((line, index) => { if (line.sign !== ' ') lastChange = index; });
    const end = lastChange < 0 ? lines.length : Math.min(lines.length, lastChange + 2);
    return lines.slice(Math.max(0, end - MAX_LINES), end);
  }

  function create({ fetchJson, onChange, agentFor } = {}) {
    let runId = '';
    let timer = null;
    let inFlight = false;
    let failures = 0;
    let generation = 0;
    let baseline = null;   // file -> diff text, as of the previous answer
    let changedAt = {};    // file -> the poll number its diff last moved on
    let movedAt = {};      // file -> when (ms) that poll answered
    let polls = 0;
    let current = null;

    function report(next) {
      const before = JSON.stringify(current);
      current = next;
      if (JSON.stringify(next) !== before && typeof onChange === 'function') onChange(next);
    }

    function hidden() {
      return typeof document !== 'undefined' && document && document.hidden === true;
    }

    function schedule(ms) {
      if (!runId) return;
      timer = setTimeout(tick, ms);
    }

    async function tick() {
      timer = null;
      if (!runId) return;
      if (inFlight || hidden()) { schedule(POLL_MS); return; }
      const mine = generation;
      inFlight = true;
      let data = null;
      try {
        data = await fetchJson(`/api/evolve/agent/live-diff?run_id=${encodeURIComponent(runId)}`);
      } catch (error) {
        data = null;
      }
      inFlight = false;
      if (mine !== generation) return;  // stopped, or restarted for another run
      if (!data || data.ok !== true || !Array.isArray(data.files)) {
        failures += 1;
        schedule(failures >= 3 ? BACKOFF_MS : POLL_MS);
        return;
      }
      failures = 0;
      absorb(data.files);
      schedule(POLL_MS);
    }

    function absorb(files) {
      polls += 1;
      const now = {};
      files.forEach(entry => {
        if (entry && typeof entry.file === 'string' && entry.file) now[entry.file] = String(entry.diff || '');
      });
      if (baseline === null) { baseline = now; return; }
      Object.keys(now).forEach(file => {
        if (baseline[file] !== now[file]) { changedAt[file] = polls; movedAt[file] = Date.now(); }
      });
      baseline = now;
      // The newest mover wins; among files that moved together, the one listed
      // first (the server lists them in git's order). A file whose diff has
      // gone back to nothing (reverted) stops being a candidate.
      let pick = '';
      Object.keys(changedAt).forEach(file => {
        if (!now[file]) return;
        if (!pick || changedAt[file] > changedAt[pick]) pick = file;
      });
      if (!pick) { if (current) report(null); return; }
      const entry = files.find(item => item && item.file === pick) || {};
      report({
        file: pick,
        added: Number(entry.added) || 0,
        removed: Number(entry.removed) || 0,
        lines: parseLastHunk(entry.diff),
        agentTitle: typeof agentFor === 'function' ? String(agentFor(pick) || '') : '',
        at: movedAt[pick],
      });
    }

    function start(id) {
      const next = String(id || '');
      if (!next || next === runId) return;
      stop();
      runId = next;
      generation += 1;
      schedule(0);
    }

    function stop() {
      generation += 1;
      if (timer !== null) clearTimeout(timer);
      timer = null;
      runId = '';
      inFlight = false;
      failures = 0;
      baseline = null;
      changedAt = {};
      movedAt = {};
      polls = 0;
      if (current) report(null);
    }

    return { start, stop, current: () => current };
  }

  window.ThomasCodeLiveDiff = { create, parseLastHunk };
})();
