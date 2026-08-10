// What a Code run produced, and how it is handed back: the run report, the
// artifact cards in the reply, and the preview documents behind them.
//
// Split out of unified_code_mode.js, which had grown past the 1500-line ceiling
// in thomas/_architecture.py. The seam is the one the stylesheets already draw
// (unified_code_results.css): everything here answers "what did Thomas make and
// can you open it", and nothing here owns the run, the stream, or the state
// machine. The long comments are load-bearing -- each one records a bug that
// was found the hard way -- and they moved with the code they explain.
//
// Loaded before unified_code_mode.js, which calls configure() once with the
// collaborators it owns (the shared state object, the HTML escaper, the
// internal-path filter, the lifecycle helpers, and render). These are classic
// scripts rather than ES modules, so injection is how a dependency is named:
// there is exactly ONE esc and ONE state, never a second copy here.
(function () {
  'use strict';

  let state = null;
  let esc = null;
  let isInternalResultPath = null;
  let lifecycle = null;
  let render = null;

  function configure(deps) {
    state = deps.state;
    esc = deps.esc;
    isInternalResultPath = deps.isInternalResultPath;
    lifecycle = deps.lifecycle;
    render = deps.render;
  }

  // Did the engine SKIP this check rather than run it? Matched on the engine's
  // own marker rather than the word "skipped", which turns up in unrelated
  // evidence such as "1 files checked, 1 skipped". Same test run_report.py uses
  // (`_SKIPPED_EVIDENCE`), so the two surfaces cannot drift.
  //
  // Module scope because BOTH the per-check rows and the headline counts need
  // it, and the rows are built first. See the long note in runReportHtml.
  function wasSkipped(item) {
    return /[A-Z][A-Z_]*_SKIPPED\b/.test(String((item && item.evidence) || ''));
  }

  function reportRow(ok, heading, label, glyph) {
    // Whole class names, never a bare `ph-` prefix with the suffix interpolated
    // after it. The icon guard scans for literal `ph-*` names, so a suffix
    // assembled at runtime is invisible to it: a bogus name injected here
    // rendered as a bullet on every "Check passed" row while
    // tests/test_every_icon_the_ui_asks_for_is_drawn.py stayed green. Written in
    // full, the name is a literal the guard can see.
    return `<div class="tc-code-technical${ok ? '' : ' is-error'}"><i class="ph ${glyph || (ok ? 'ph-check-circle' : 'ph-warning')}"></i><div><strong>${esc(heading)}</strong><code>${esc(label)}</code></div></div>`;
  }

  function reportSection(title, rows) {
    if (!rows.length) return '';
    return `<details class="tc-code-progress-history"><summary>${esc(title)} (${rows.length})</summary><div>${rows.join('')}</div></details>`;
  }

  // CAP-141: structured post-run report (attempts / validations / open risks /
  // attention pointers / rubric mapping), rendered as collapsible sections with
  // the existing technical-log styling. Defensive: an absent or malformed
  // report renders nothing — older turns have no report field.
  function runReportHtml(report) {
    if (!report || typeof report !== 'object') return '';
    // What KIND of run is this card grading? The server records the outcome
    // word on the report (run_report.build_run_report); older turns predate it
    // and fall through to the build ladder below, which is what they always got.
    const outcome = String(report.outcome || '');
    // An answer is not a build, so it gets no build-verification scorecard.
    // A `conversation` run replied without changing a single file -- there is
    // nothing a build check could have checked -- yet it was rendered with the
    // full card, and every number on that card was therefore about a build that
    // never happened. Measured 2026-08-05: an explain-only run's card carried
    // two "open risks" manufactured from the harness's own injected no-op
    // error. One line says WHY there is no card, which is more sight than
    // either silence or a scorecard of fabricated counts.
    if (outcome === 'conversation') {
      return '<div class="tc-code-result-note"><span><i class="ph ph-info" aria-hidden="true"></i>This was an answer, not a build — nothing to verify.</span></div>';
    }
    const list = value => Array.isArray(value) ? value : [];
    const attempts = list(report.attempts).map(item => reportRow(!/fail/i.test(String(item.outcome || '')), `Pass ${item.pass || '?'} · ${String(item.outcome || 'unknown')}`, `${String(item.goal || '')} → ${String(item.exit_state || '')}`));
    // The headline already separates a skipped check from a passing one; this
    // row did not. `passed` is the absence of an error, so a check that never
    // ran arrives flagged true, and the row rendered "Check passed" under a
    // green tick beside evidence reading BROWSER_SMOKE_SKIPPED. Measured: the
    // same card said "1/1 check passed · 1 check skipped" on its face and
    // "Check passed / Check passed" in the Validations section a reviewer opens
    // to see WHICH check -- the detail surface was the one stating the false
    // thing. Failed still outranks skipped, matching the headline's ordering.
    const validations = list(report.validations).map(item => {
      const failed = item.passed !== true;
      const skippedItem = !failed && wasSkipped(item);
      const heading = failed ? 'Check failed' : (skippedItem ? 'Check skipped' : 'Check passed');
      const label = `${String(item.command || item.kind || 'check')} — ${String(item.evidence || '')}`;
      return reportRow(!failed, heading, label, skippedItem ? 'ph-info' : '');
    });
    const risks = list(report.open_risks).map(item => reportRow(false, String(item.risk || 'open risk'), String(item.detail || '')));
    const pointers = list(report.attention_pointers).map(item => reportRow(true, `#${item.rank || '?'} ${String(item.target || '')}`, String(item.why || '')));
    const rubric = list(report.rubric_mapping).map(item => reportRow(item.status === 'met', `${String(item.status || 'unverified')} · ${String(item.criterion || '')}`, String(item.evidence || '')));
    const sections = [
      reportSection('Attempts', attempts),
      reportSection('Validations', validations),
      reportSection('Open risks', risks),
      reportSection('Where to look first', pointers),
      reportSection('Rubric mapping', rubric),
    ].join('');
    if (!sections) return '';
    const riskCount = risks.length;
    const checks = list(report.validations);

    // A check the engine SKIPPED is not a check that passed.
    //
    // `passed` is derived server-side from the absence of an error
    // (run_report.py: `"passed": event.get("is_error") is not True`). When no
    // browser is installed, smoke_html_artifacts returns attempted=False and
    // build_verify emits `BROWSER_SMOKE_SKIPPED: ...` with is_error unset -- so a
    // check that never ran arrives here flagged passed, and got counted in
    // "2/2 checks passed". The evidence string says SKIPPED, so the honest count
    // was available; nothing was reading it.
    //
    // NOT reproducible on this machine: Chrome is present, so 0 of 47 real
    // reports carry a skip. On a fresh install without browsers, every web run
    // would have read "2/2 checks passed" with one of the two never having run.
    // The run's open-risk list already flags the unopened page
    // (run_report._unopened_page_risks), so the tone was right; only the count
    // was wrong.
    //
    // `wasSkipped` is module scope, above -- the per-check rows need it too.
    const skipped = checks.filter(wasSkipped).length;
    const ran = checks.length - skipped;
    const passed = checks.filter(item => item.passed === true && !wasSkipped(item)).length;
    const failed = checks.filter(item => item.passed !== true).length;

    // The rubric is where a run admits what it did NOT check, and it was not
    // reaching the verdict at all -- the headline was computed from
    // `validations` alone, so a run whose rubric said "unverified" still
    // announced "Checks passed" and buried the admission inside a collapsed
    // section nobody opens.
    //
    // Seen on the owner's Nova calculator: two engine checks passed, the second
    // with evidence reading "browser boot clean; boot only" -- it loaded the
    // page and clicked nothing. Meanwhile five nav destinations, the Ctrl+K
    // command palette, both icon buttons and Clear were all inert, and
    // `200 + 10 %` returned 2.1. None of that could have been caught by a check
    // that never pressed a button, and the report said so; the verdict did not.
    // An unexamined requirement is not a passing one.
    //
    // This discriminates rather than blanket-warns: across 43 real reports it
    // moves 7 off a false green and leaves the 5 that genuinely checked their
    // requirements still reading "Checks passed".
    const unverified = list(report.rubric_mapping)
      .filter(item => String(item.status || '').toLowerCase() === 'unverified').length;

    // A verdict, then the numbers. It used to read "Run report · 1 pass · 2
    // checks · 0 open risks" -- counts with nothing said about them, where
    // "1 pass" means one EDIT pass and is read as one test passing. This is the
    // line that answers "did the thing I asked for work", so it says so.
    //
    // "Nothing was checked" is its own state on purpose. A run with no
    // validations at all must not look like a run that passed, which is exactly
    // the confusion the whole report exists to prevent.
    //
    // A STOPPED run is its own state too, and it comes first: the person ended
    // the run before verification could finish, so grading it as an unverified
    // build charges them with their own decision. Measured 2026-08-05, the face
    // read "Nothing was checked · 1 requirement unverified · 2 open risks" on a
    // run its owner had stopped on purpose. The face now says only what
    // happened before the stop; the full record stays behind Show details.
    //
    // The unverified branch leads with what WAS verified and then scopes what
    // was not, in one sentence. Its old headline pair -- "Not checked against
    // your ask" rendered directly above "2/2 checks passed" -- was two true
    // statements that read as a self-contradiction, because the headline named
    // only the gap and the facts line named only the pass. The tone stays
    // is-unknown: passing the automatic checks is not the same as the ask
    // having been verified, and the card still says so, coherently.
    let tone = 'is-good';
    let verdict = 'Checks passed';
    let askNotVerified = false;
    if (outcome === 'stopped') { tone = 'is-unknown'; verdict = ran ? 'Stopped during verification' : 'Stopped before verification could run'; }
    else if (failed > 0) { tone = 'is-bad'; verdict = failed === ran ? 'Checks failed' : 'Some checks failed'; }
    else if (!ran) { tone = 'is-unknown'; verdict = 'Nothing was checked'; }
    else if (unverified) { tone = 'is-unknown'; verdict = `Passed ${ran} automatic check${ran === 1 ? '' : 's'}`; askNotVerified = true; }
    else if (riskCount) { tone = 'is-warn'; verdict = 'Passed, with things to look at'; }

    const facts = [];
    if (outcome === 'stopped') {
      // Only what actually happened before the stop. No open-risks or
      // requirement-unverified language: a run nobody let finish has not
      // earned charges, and the risks it does carry are the stop's own
      // bookkeeping. The sections below keep the complete record.
      if (ran) facts.push(`${passed}/${ran} check${ran === 1 ? '' : 's'} passed before the stop`);
      if (failed) facts.push(`${failed} check${failed === 1 ? '' : 's'} failed before the stop`);
    } else {
      // In the ask-not-verified branch the headline already carries the pass
      // count, so repeating "2/2 checks passed" under it would rebuild the
      // old contradictory pair one line down.
      if (ran && !askNotVerified) facts.push(`${passed}/${ran} check${ran === 1 ? '' : 's'} passed`);
      if (skipped) facts.push(`${skipped} check${skipped === 1 ? '' : 's'} skipped`);
      if (unverified) {
        facts.push(askNotVerified
          ? (unverified === 1 ? 'your specific ask was not separately verified' : `${unverified} parts of your ask were not separately verified`)
          : `${unverified} requirement${unverified === 1 ? '' : 's'} unverified`);
      }
      facts.push(riskCount ? `${riskCount} open risk${riskCount === 1 ? '' : 's'}` : 'no open risks');
      if (attempts.length > 1) facts.push(`${attempts.length} edit passes`);
    }

    // WHICH requirements, not just how many.
    //
    // The headline names a problem -- "Not checked against your ask" -- and the
    // answer to "which ones?" sat behind TWO closed disclosures, under a section
    // headed "Rubric mapping" that gives no hint it holds the answer. Measured on
    // the ledger run: closedDisclosuresToOpen = 2 for a card whose whole point is
    // that six things went unchecked. Naming them is what turns the verdict into
    // something a person can act on -- these are the things to try by hand.
    //
    // Two, not three, and each given enough room to be read.
    //
    // Three fitted the box only by starving the last one: against real criteria
    // the line rendered "... · So there are 3 visible headers over 4 visib... ·
    // A..." -- a stub that names nothing and reads as damage. Two at 38
    // characters each leaves both legible on one line.
    //
    // No trailing "+N more" either: the line is ellipsised when it overflows, so
    // a suffix is the FIRST thing cut -- measured at 548px against a 560px box
    // with "+3 more" invisible. The count it would have carried is already
    // spelled out one line above ("6 requirements unverified"), so the honest
    // total survives and clipping only ever costs detail.
    const clip = text => (text.length > 38 ? `${text.slice(0, 37).trimEnd()}…` : text);
    // Not on a stopped run: naming unverified requirements is the same
    // requirement-unverified language the stopped face exists to avoid, and
    // the person already knows why nothing was checked -- they stopped it.
    const unverifiedNames = (outcome === 'stopped' ? [] : list(report.rubric_mapping))
      .filter(item => String(item.status || '').toLowerCase() === 'unverified')
      .map(item => String(item.criterion || '').trim())
      .filter(Boolean)
      .slice(0, 2)
      .map(clip);
    const uncheckedLine = unverifiedNames.length
      ? `<small class="tc-code-verdict-unchecked">${esc(`Not checked: ${unverifiedNames.join(' · ')}`)}</small>`
      : '';

    const glyph = tone === 'is-bad' ? 'ph-warning-circle' : (tone === 'is-warn' ? 'ph-warning' : (tone === 'is-unknown' ? 'ph-info' : 'ph-check-circle'));
    // The facts render as STRUCTURED CELLS, not a raw dot-joined sentence
    // (owner, 2026-08-10: "organize the information, not just raw text
    // output" / "the passed-2-automatic-checks at the bottom i don't like").
    // A fact that leads with a number becomes a tile with the number large;
    // prose facts stay a quiet chip. Same honest wording, readable shape.
    const factTile = fact => {
      const m = /^([\d/]+)\s+(.*)$/.exec(fact);
      if (m) return `<span class="tc-code-stat"><b>${esc(m[1])}</b><i>${esc(m[2])}</i></span>`;
      return `<span class="tc-code-stat is-prose"><i>${esc(fact)}</i></span>`;
    };
    return `<details class="tc-code-saved-activity tc-code-run-report ${tone}${riskCount ? ' has-issues' : ''}" data-saved="true">
      <summary>
        <span class="tc-code-verdict"><i class="ph ${glyph}" aria-hidden="true"></i><span class="tc-code-verdict-text"><strong>${esc(verdict)}</strong><span class="tc-code-stats">${facts.map(factTile).join('')}</span>${uncheckedLine}</span></span>
        <span class="tc-code-verdict-more">Show details</span>
      </summary>
      <div class="tc-code-technical-log">${sections}</div>
    </details>`;
  }

  // Does this page ask for the network? The embedded preview's CSP blocks
  // every outbound connection, so a perfectly working generated app opens
  // straight into its own error state -- measured (w2-code-network,
  // w2-code-impossible): "Live feed unavailable", "Google sign-in is still
  // loading" -- with nothing anywhere saying the PREVIEW is the reason. This
  // scan exists so the viewer can SAY so (one visible line, see viewerHtml),
  // never to reject or reshape anything: a flagged page still renders exactly
  // as before. Prose like "data is fetched daily" and plain <a href="https://"
  // links do not count -- an anchor navigates, it does not connect.
  function htmlWantsNetwork(html) {
    const s = String(html || '');
    return /\bfetch\s*\(/.test(s)
      || /\bnew\s+(?:XMLHttpRequest|WebSocket|EventSource)\b/.test(s)
      || /\bnavigator\.sendBeacon\b/.test(s)
      || /<(?:script|img|iframe|audio|video|source)\b[^>]*\bsrc\s*=\s*["']https?:\/\//i.test(s)
      || /<link\b[^>]*\bhref\s*=\s*["']https?:\/\//i.test(s);
  }

  function artifactHtml(artifact) {
    const file = String(artifact.file || '');
    const url = `/api/evolve/agent/artifact/${encodeURIComponent(state.activeId)}/${file.split('/').map(encodeURIComponent).join('/')}`;
    const title = `<strong>${esc(file)}</strong><a href="${url}" target="_blank" rel="noopener">Open</a>`;
    if (artifact.kind === 'html') return `<section class="tc-code-artifact"><header>${title}</header><div class="tc-code-artifact-shot"><iframe src="${url}" sandbox="allow-scripts allow-forms allow-same-origin" title="Preview ${esc(file)}" tabindex="-1" scrolling="no"></iframe></div></section>`;
    if (artifact.kind === 'image') return `<section class="tc-code-artifact"><header>${title}</header><img src="${url}" alt="Generated artifact ${esc(file)}"></section>`;
    // PDF/schematic artifacts preview inline too (parity with chat), not just a link.
    if (artifact.kind === 'pdf' || /\.pdf(?:$|[?#])/i.test(file)) return `<section class="tc-code-artifact"><header>${title}</header><iframe src="${url}#toolbar=0&navpanes=0&view=FitH" title="Preview ${esc(file)}"></iframe></section>`;
    if (/\.svg(?:$|[?#])/i.test(file)) return `<section class="tc-code-artifact"><header>${title}</header><img src="${url}" alt="Generated artifact ${esc(file)}"></section>`;
    return `<section class="tc-code-artifact is-link"><header>${title}</header><span>${esc(artifact.kind || 'artifact')} result</span></section>`;
  }

  // What Thomas just made, named and openable, inside the reply itself.
  // The turn already carries artifacts -- [{file:'trey-badlands.html',kind:'html'}]
  // -- and all the reply said was "1 result ready". A count is not a delivery:
  // the owner had to follow a build by typing "where is it" and then "what's the
  // full directory name". Handing back a thing you cannot open is the same as
  // not handing it back.
  function artifactCardsHtml(turn, turnKey) {
    const items = (turn.artifacts || []).filter(a => a && a.file && !isInternalResultPath(a.file));
    if (!items.length) return '';
    const rows = items.map(a => {
      const file = String(a.file);
      const playable = /\.x?html?$/i.test(file);
      const doc = state.artifactDocs && state.artifactDocs[file];
      // Keyed per turn: the same file is listed by every turn that touched it,
      // so keying by name alone opened six copies of the game at once.
      const slot = `${turnKey}::${file}`;
      const open = !!(state.artifactOpen && state.artifactOpen[slot]);
      // A live thumbnail of the real thing, exactly as Chat shows a deliverable:
      // you can see what it is before you commit to opening it.
      const thumb = (playable && doc)
        ? `<span class="tc-code-artifact-thumb"><iframe tabindex="-1" aria-hidden="true" scrolling="no" sandbox="allow-scripts allow-same-origin" src="${esc(doc)}"></iframe></span>`
        : `<span class="tc-code-artifact-thumb is-icon"><i class="ph ${playable ? 'ph-play-circle' : 'ph-file'}"></i></span>`;
      const hint = playable ? 'Click to open it beside the chat' : 'Click to view';
      // No inline stage. Expanding in place dropped a tall frame into the
      // middle of the transcript, so the result became something you scroll
      // past rather than something you use, and a full-screen app never fits
      // in a card anyway. It opens in the viewer panel instead — see
      // `viewerHtml`.
      const expanded = '';
      // Chat's deliverable card carries a download beside it; a result you can
      // only look at inside Thomas is not really yours yet.
      const save = `<button class="tc-code-artifact-save" data-code-save-artifact="${esc(file)}" type="button" title="Download ${esc(file)}" aria-label="Download ${esc(file)}"><i class="ph ph-download-simple" aria-hidden="true"></i></button>`;
      // Open the real thing in a real tab. Expanding in place is fine for a
      // glance, but it drops a tall frame into the middle of the transcript and
      // the page it made is then something you scroll past rather than use --
      // a full-screen app does not fit in a card. Chat gives a deliverable this
      // escape hatch and Code did not, so the only way out was Download.
      // Built the same way `artifactHtml` builds it, from the conversation this
      // turn belongs to. A turn's artifact entry is only {file, kind, ext} --
      // it carries no URL of its own.
      const openUrl = state.activeId
        ? `/api/evolve/agent/artifact/${encodeURIComponent(state.activeId)}/${file.split('/').map(encodeURIComponent).join('/')}`
        : '';
      const openTab = (playable && openUrl)
        ? `<a class="tc-code-artifact-pop" href="${esc(openUrl)}" target="_blank" rel="noopener noreferrer" title="Open ${esc(file)} in a new tab" aria-label="Open ${esc(file)} in a new tab"><i class="ph ph-arrow-square-out" aria-hidden="true"></i></a>`
        : '';
      // The combined card the owner asked for (2026-08-10): thumbnail plus a
      // REAL action row in plain words — Open in chat, Open in separate
      // window, Download — instead of two unlabeled icons.
      const actions = `<div class="tc-code-artifact-actions">
        <button class="tc-code-artifact-act is-primary" data-code-open-artifact="${esc(file)}" data-code-artifact-slot="${esc(slot)}" type="button">Open in chat</button>
        ${(playable && openUrl) ? `<a class="tc-code-artifact-act" href="${esc(openUrl)}" target="_blank" rel="noopener noreferrer">Open in separate window</a>` : ''}
        <button class="tc-code-artifact-act" data-code-save-artifact="${esc(file)}" type="button">Download</button>
      </div>`;
      return `<div class="tc-code-artifact">
        <div class="tc-code-artifact-row">
          <button class="tc-code-artifact-open" data-code-open-artifact="${esc(file)}" data-code-artifact-slot="${esc(slot)}" type="button" aria-expanded="${open ? 'true' : 'false'}">
            ${thumb}
            <span class="tc-code-artifact-meta">
              <span class="tc-code-artifact-name">${esc(file)}</span>
              <span class="tc-code-artifact-verb">${hint}</span>
            </span>
          </button>
        </div>${actions}${expanded}
      </div>`;
    }).join('');
    // "See every change" now renders ABOVE the closing rule (turnHtml owns
    // it) — the card below the line carries only the deliverable itself.
    return `<div class="tc-code-artifacts"><div class="tc-code-artifacts-head">${items.length === 1 ? 'Thomas made this' : `Thomas made ${items.length} things`}</div>${rows}</div>`;
  }

  // Fetch a result's document once and keep it, so the card can show a live
  // thumbnail and expand in place without re-reading on every render.
  // `quiet` skips the redraw. render() rewrites the thread's innerHTML, which
  // DESTROYS every preview iframe and restarts its navigation from scratch.
  // Resolving four thumbnails one at a time therefore reloaded all of them four
  // times, and a frame recreated before it finished never painted -- the game
  // sat on about:blank showing a broken-document icon while the server was
  // serving it perfectly. Resolve the batch, then draw once.
  async function ensureArtifactDoc(path, quiet) {
    const file = String(path || '');
    if (!file) return false;
    state.artifactDocs = state.artifactDocs || {};
    if (state.artifactDocs[file] !== undefined) return true;
    const token = lifecycle().contextToken(state);
    if (!token.id) return false;
    // A real loopback origin, the same service Chat previews deliverables
    // through. srcdoc has no origin and no base URL, so anything the page loads
    // at RUNTIME fails: Thomas moved a game's renderer to a dynamic loader and
    // the preview 404'd it 51 times and silently fell back to the old canvas.
    //
    // One origin serves the WHOLE project, so ask for it once and address the
    // other files within it. Asking per file re-minted the grant and tore down
    // the previous one, which blanked a card that was already showing a page:
    // opening the game killed the thumbnail of the shell page beside it.
    let url = null;
    const base = state.previewBase && state.previewBase.cid === token.id ? state.previewBase.url : '';
    if (base) url = `${base}/${file.split('/').map(encodeURIComponent).join('/')}`;
    else {
      try {
        const r = await fetch(`/api/evolve/agent/conversations/${encodeURIComponent(token.id)}/preview?path=${encodeURIComponent(file)}`);
        const d = await r.json();
        if (r.ok && d && d.ok && d.url) url = String(d.url);
      } catch (e) { url = null; }
    }
    if (!lifecycle().contextMatches(state, token)) return false;
    if (!url) return false;
    if (!base) {
      // Everything up to the capability; the tail is per file.
      const cut = url.lastIndexOf('/');
      if (cut > 0) state.previewBase = { cid: token.id, url: url.slice(0, cut) };
    }
    state.artifactDocs[file] = url;
    // Learn whether the page asks for the network BEFORE the redraw that shows
    // it, through the same validated read the asset inliner uses. Awaited on
    // purpose: a flag arriving after render() would need another render, and
    // render() rewrites innerHTML, which destroys every live preview iframe
    // (see the note above). One extra file read per HTML artifact, once.
    if (/\.x?html?$/i.test(file)) {
      state.artifactNet = state.artifactNet || {};
      if (state.artifactNet[file] === undefined) {
        try {
          const body = await readProjectFile(token.id, file);
          state.artifactNet[file] = body === null ? false : htmlWantsNetwork(body);
        } catch (e) { state.artifactNet[file] = false; }
      }
    }
    if (!quiet) render();
    return true;

  }

  // Pull the documents for what a conversation produced so the results are
  // VISIBLE on arrival rather than after a click. Capped, newest turns first.
  const _ARTIFACT_THUMB_BUDGET = 4;
  async function hydrateArtifactThumbnails() {
    const turns = (state.conversation && state.conversation.turns) || [];
    const wanted = [];
    for (let i = turns.length - 1; i >= 0 && wanted.length < _ARTIFACT_THUMB_BUDGET; i -= 1) {
      const turn = turns[i];
      if (!turn || turn.role !== 'agent') continue;
      for (const a of turn.artifacts || []) {
        const file = a && a.file ? String(a.file) : '';
        if (!file || isInternalResultPath(file) || !/\.x?html?$/i.test(file)) continue;
        if (wanted.includes(file)) continue;
        wanted.push(file);
        if (wanted.length >= _ARTIFACT_THUMB_BUDGET) break;
      }
    }
    let resolved = false;
    for (const file of wanted) {
      try { resolved = (await ensureArtifactDoc(file, true)) || resolved; } catch (e) { /* one bad result must not stop the rest */ }
    }
    if (resolved) render();
  }

  // Open what the last completed turn produced. Prefers a page, because a page
  // is the thing you can actually look at; falls back to whatever else it made.
  async function presentNewestResult() {
    const turns = (state.conversation && state.conversation.turns) || [];
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      const turn = turns[i];
      if (!turn || turn.role !== 'agent' || !turn.ok) continue;
      const made = (turn.artifacts || []).filter(a => a && a.file && !isInternalResultPath(a.file));
      if (!made.length) return false;
      const pick = made.find(a => /\.x?html?$/i.test(String(a.file))) || made[0];
      const file = String(pick.file);
      state.artifactOpen = state.artifactOpen || {};
      state.artifactOpen[`${turn.run_id || turn.ts || '0'}::${file}`] = true;   // in the conversation
      try { return await ensureArtifactDoc(file); } catch (e) { return false; }
    }
    return false;
  }

  function readProjectFile(conversationId, path) {
    return fetch(`/api/evolve/agent/conversations/${encodeURIComponent(conversationId)}/file?path=${encodeURIComponent(path)}`)
      .then(r => r.json())
      .then(d => (d && d.ok ? String(d.content || '') : null))
      .catch(() => null);
  }

  // A previewed page is shown with srcdoc, which has NO project base URL: a
  // relative <script src="renderer.js"> resolves against the Thomas server and
  // 404s, so a multi-file build would preview as the page minus everything it
  // depends on. Thomas had just split a game's chase-camera renderer into its
  // own file, which would have rendered here as a game with no renderer.
  //
  // The referenced local files are pulled through the SAME validated read as the
  // page itself and inlined, so nothing new is exposed and no new route exists.
  // Remote URLs are left alone -- the sandbox has no same-origin and the CSP
  // still applies to them.
  async function inlineLocalAssets(conversationId, html, pagePath) {
    const dir = String(pagePath || '').includes('/') ? String(pagePath).replace(/\/[^/]*$/, '/') : '';
    const isLocal = ref => ref && !/^(?:[a-z]+:)?\/\//i.test(ref) && !ref.startsWith('data:') && !ref.startsWith('#');
    const resolve = ref => (ref.startsWith('/') ? ref.slice(1) : dir + ref).split('?')[0].split('#')[0];
    let out = html;

    const scripts = [...html.matchAll(/<script\b([^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*)>\s*<\/script\s*>/gi)];
    for (const m of scripts) {
      if (!isLocal(m[2])) continue;
      const body = await readProjectFile(conversationId, resolve(m[2]));
      if (body === null) continue;
      out = out.replace(m[0], `<script>\n/* inlined from ${m[2]} for preview */\n${body}\n</script>`);
    }
    const links = [...html.matchAll(/<link\b[^>]*\bhref\s*=\s*["']([^"']+\.css)["'][^>]*>/gi)];
    for (const m of links) {
      if (!isLocal(m[1])) continue;
      const body = await readProjectFile(conversationId, resolve(m[1]));
      if (body === null) continue;
      out = out.replace(m[0], `<style>\n/* inlined from ${m[1]} for preview */\n${body}\n</style>`);
    }
    return out;
  }

  // ---------- The viewer: what Thomas made, beside the conversation ----------
  // A panel that slides in from the right, the way a result is normally handed
  // to you. The card is the snapshot; clicking it brings the real thing over
  // here, where it gets the height of the window instead of a slot in the
  // transcript. From here it can go full-bleed across Thomas, or out into its
  // own browser tab.
  function artifactUrlFor(file) {
    if (!state.activeId) return '';
    return `/api/evolve/agent/artifact/${encodeURIComponent(state.activeId)}/${String(file).split('/').map(encodeURIComponent).join('/')}`;
  }

  // WATCH Thomas play: the live game footage is the star. Frames stream from
  // the server-side playtest browser; the caption says what Thomas just did;
  // the verdict lands at the end. (owner, 2026-08-10: he wants to see it play,
  // not read about it.)
  function renderPlaytestPanel() {
    // The viewer shows only the LIVE footage while Thomas tests; the verdict
    // and its recommendation buttons render in the main chat (playtestChatCard).
    const frame = state.viewerPlayFrame;
    const caption = state.viewerPlayCaption || '';
    const see = state.viewerPlaySee || '';
    if (!state.viewerPlaying && !frame) return '';
    const img = frame
      ? `<img class="tc-code-playtest-frame" alt="Thomas testing" src="data:image/png;base64,${frame}">`
      : `<div class="tc-code-playtest-frame is-empty">Opening it…</div>`;
    return `<div class="tc-code-playtest is-live">
      <div class="tc-code-playtest-stage">
        ${img}
        <div class="tc-code-playtest-hud">
          <span class="tc-code-playtest-badge"><span class="tc-code-playtest-pulse"></span>Thomas is testing</span>
          ${caption ? `<span class="tc-code-playtest-move">${esc(caption)}</span>` : ''}
        </div>
        ${see ? `<div class="tc-code-playtest-see">${esc(see)}</div>` : ''}
      </div>
    </div>`;
  }

  // The verdict as a card in the MAIN CHAT: what Thomas found, then 1-3
  // recommendation buttons he generated, then "or tell Thomas what to do".
  // Clicking a recommendation starts a real fix run; the free-type row just
  // focuses the composer. (owner, 2026-08-10)
  function playtestChatCardHtml() {
    const result = state.playtestResult;
    if (!result || !result.report) return '';
    const report = result.report;
    const bugs = Array.isArray(report.bugs) ? report.bugs.filter(Boolean) : [];
    const recs = (Array.isArray(report.recommendations) ? report.recommendations : [])
      .filter(r => r && r.label && r.prompt).slice(0, 3);
    const tone = report.works === false ? 'is-bad' : (report.difficulty && /too (hard|easy)/i.test(String(report.difficulty)) ? 'is-warn' : 'is-good');
    const recButtons = recs.map((r, i) => `<button class="tc-code-rec${i === 0 ? ' is-primary' : ''}" type="button" data-code-playtest-rec="${esc(String(r.prompt))}">${esc(String(r.label))}</button>`).join('');
    return `<article class="tc-code-turn is-agent tc-code-playtest-card ${tone}">
      <div class="tc-code-message-head"><span class="tc-code-avatar is-anvil" aria-hidden="true"><svg viewBox="0 0 256 256" aria-hidden="true"><path d="M240 60h-92a12 12 0 0 0 0 24h6.6c-4 24.5-22.8 44-47 48.6C82.9 137.4 64 121.4 64 96V84h12a12 12 0 0 0 0-24H24a12 12 0 0 0 0 24h16v12c0 34.6 24.7 58.5 56 63.4v10.2c0 11-4.7 21.4-13 28.6l-18.9 16.5A12 12 0 0 0 72 236h112a12 12 0 0 0 7.9-21.1L173 198.4a38.2 38.2 0 0 1-13-28.6v-10.6c37.5-6 66.2-35 70.7-71.2H240a12 12 0 0 0 0-24Z"/></svg></span><strong>Thomas</strong><small>tested it</small></div>
      <div class="tc-code-turn-body">
        <div class="tc-code-playtest-verdictline">${esc(String(report.summary || report.verdict || 'Tested it.'))}</div>
        <div class="tc-code-playtest-facts">
          ${report.difficulty && report.difficulty !== 'n/a' ? `<span class="tc-code-stat"><b>${esc(String(report.difficulty))}</b><i>difficulty</i></span>` : ''}
          ${report.fun ? `<span class="tc-code-stat is-prose"><i>${esc(String(report.fun))}</i></span>` : ''}
          ${bugs.length ? `<span class="tc-code-stat"><b>${bugs.length}</b><i>bug${bugs.length === 1 ? '' : 's'}</i></span>` : ''}
        </div>
        ${recs.length ? `<div class="tc-code-rec-head">What do you want to do?</div><div class="tc-code-recs">${recButtons}<button class="tc-code-rec is-type" type="button" data-code-playtest-type="1">or tell Thomas…</button></div>` : ''}
      </div>
    </article>`;
  }

  function viewerHtml() {
    const open = state.viewer && state.viewer.file;
    if (!open) return '';
    const file = String(state.viewer.file);
    const docBase = (state.artifactDocs && state.artifactDocs[file]) || artifactUrlFor(file);
    const doc = state.viewerPlaying && (/^https?:/i.test(String(docBase)) || String(docBase).startsWith('/'))
      ? `${docBase}${String(docBase).includes('?') ? '&' : '?'}thomas_play=1`
      : docBase;
    const full = !!state.viewer.full;
    // One visible line when the page asks for the network: this embedded frame
    // is served connect-src 'self', so the app's fetches fail HERE by design
    // and used to fail silently -- the owner's first sight of a working build
    // was its own error state, blamed on the build. The standalone tab IS
    // allowed outbound https/wss (deliverable_aiohttp._apply_headers), so the
    // notice points at the way that works. Sight, not a gate: the preview
    // still renders exactly as before. Styled inline because this module owns
    // only the notice, not the stylesheet.
    const netNotice = (state.artifactNet && state.artifactNet[file])
      ? `<div class="tc-code-viewer-netnote" style="display:flex;align-items:center;gap:.5em;padding:.4em .9em;font-size:.8125em;opacity:.85;"><i class="ph ph-info" aria-hidden="true"></i><span>This embedded preview blocks internet access — <a href="${esc(artifactUrlFor(file))}" target="_blank" rel="noopener noreferrer">open it in its own tab</a> for live data.</span></div>`
      : '';
    // `allow-same-origin` is withheld on purpose: the frame only has to render.
    return `<aside class="tc-code-viewer${full ? ' is-full' : ''}" role="dialog" aria-label="${esc(file)}">
      <header class="tc-code-viewer-head">
        <div class="tc-code-viewer-title"><i class="ph ph-browser" aria-hidden="true"></i><strong>${esc(file)}</strong></div>
        <div class="tc-code-viewer-tools">
          <button type="button" data-code-viewer-play aria-pressed="${state.viewerPlaying ? 'true' : 'false'}" title="${state.viewerPlaying ? 'Stop the test' : 'Let Thomas test it'}" aria-label="${state.viewerPlaying ? 'Stop the test' : 'Let Thomas test it'}"${state.viewerPlaying ? ' class="is-playing"' : ''}><svg viewBox="0 0 256 256" width="17" height="17" fill="currentColor" aria-hidden="true"><path d="M176 100a12 12 0 1 1-12 12 12 12 0 0 1 12-12Zm28 20a12 12 0 1 0 12 12 12 12 0 0 0-12-12ZM104 116H92v-12a8 8 0 0 0-16 0v12H64a8 8 0 0 0 0 16h12v12a8 8 0 0 0 16 0v-12h12a8 8 0 0 0 0-16Zm141.9 60.9a36 36 0 0 1-53.4 6.3l-.4-.4-30.7-28.8H94.6l-30.7 28.8-.4.4A36 36 0 0 1 4 156.4a35 35 0 0 1 .8-4.4L27.4 61A44 44 0 0 1 70.2 28h115.6A44 44 0 0 1 228.6 61l22.6 91a35 35 0 0 1 .8 4.4 35.7 35.7 0 0 1-6.1 20.5ZM185.8 132a28 28 0 0 0 27.2-21.3l.1-.5A28 28 0 0 0 185.8 76H70.2A28 28 0 0 0 43 97.7l-22.6 91A20 20 0 0 0 20 156.4a19.9 19.9 0 0 0 33.9 11.7L86.3 137a8 8 0 0 1 5.5-2.2h72.4a8 8 0 0 1 5.5 2.2l32.4 30.4A20 20 0 0 0 236 156.4a19.6 19.6 0 0 0-.4-3.9Z"/></svg></button>
          <button type="button" data-code-viewer-full aria-pressed="${full ? 'true' : 'false'}" title="${full ? 'Shrink back beside the chat' : 'Expand to fill Thomas'}" aria-label="${full ? 'Shrink back beside the chat' : 'Expand to fill Thomas'}"><i class="ph ${full ? 'ph-corners-in' : 'ph-corners-out'}" aria-hidden="true"></i></button>
          <a href="${esc(artifactUrlFor(file))}" target="_blank" rel="noopener noreferrer" title="Open in a new browser tab" aria-label="Open in a new browser tab"><i class="ph ph-arrow-square-out" aria-hidden="true"></i></a>
          <button type="button" data-code-viewer-close title="Close" aria-label="Close"><i class="ph ph-x" aria-hidden="true"></i></button>
        </div>
      </header>
      <!-- allow-modals: this is the surface the owner actually uses the app on, so
           confirm()/alert()/prompt() have to work here. Without it the sandbox makes
           confirm() return false and show nothing, and every generated
           confirm-before-delete button is silently dead -- measured on a habit
           tracker whose Reset did nothing at all, no dialog and no error, because
           its "if (!confirm(...)) return;" guard took the early exit every time.
           NB: no backticks in this comment -- it sits inside a template literal,
           and quoting that snippet with them closed the literal and turned the
           rest of the function into a syntax error that killed all of Code mode.
           allow-downloads, same reason again: an Export CSV button did nothing here
           while the identical bytes on a plain http server downloaded the file at
           once. Any generated export/save/report button was dead.
           allow-pointer-lock, same reason: a generated FPS gates its mouse-look on
           "document.pointerLockElement === canvas", which is never true without the
           token, so the player can shoot but cannot TURN. Two of the owner's own
           deliverables call requestPointerLock.
           Deliberately NOT added to the transcript thumbnail or the drawer shot
           (unified_code_results.js:184, :212): both are tabindex="-1" decoration,
           and a 168px picture must never be able to pop a dialog over the chat or
           swallow the mouse cursor. -->
      <!-- allow-same-origin is what lets a multi-file deliverable load its OWN
           styles.css and game.js. Without it the document has an opaque origin, so
           default-src 'self' matches nothing and every relative subresource is
           refused. The panel then shows unstyled Times New Roman markup over a dead
           300x150 canvas, while the same file in a new tab is the finished app.
           Isolated on a standalone page that never re-renders, after a 9s settle:
             without: window.origin 'null', cssRules SecurityError, fetch('styles.css')
                      TypeError, canvas 300x150
             with   : window.origin real, cssRules 154, fetch 200, canvas 1280x800
           Chromium reports the refusals as net::ERR_ABORTED rather than csp, which
           reads like a cancelled request and is why this looked like a re-render.
           NB read window.origin, not location.origin -- the latter returns the URL's
           origin even in an opaque document and says 'not opaque' when it is.
           The two decorative previews (:184, :212) already carry allow-same-origin;
           this interactive one was the only frame without it. Safe here because the
           artifact is served from its OWN port, a different origin from the shell,
           so the frame cannot reach Thomas's DOM or cookies -- and the response CSP
           already grants the same token at the sandbox layer. -->
      <!-- allow="fullscreen; clipboard-write" is the SAME defect one layer over.
           Sandbox tokens are not the only gate: fullscreen and the async clipboard
           are Permissions Policy features whose default allowlist is "self", which
           means the embedding page has to delegate them or a cross-origin frame is
           refused. The artifact is served from its own 127.0.0.1:PORT, so it IS
           cross-origin here, and nothing delegated -- so both were dead in the
           viewer while the identical bytes worked when opened in a tab. Two of the
           owner's own deliverables, driven through this route:
             colortoy.html Copy button   top level: says "Copied!"  framed: says "Copy"
             snake.html    F key         top level: fullscreen      framed: nothing
           Neither reports an error. colortoy's handler is
           "await navigator.clipboard.writeText(...)" with no catch, so the reject
           aborts it before the label update -- the button is silently inert. snake
           prints "F fullscreen" on its own start screen and then ignores the key.
           Census over 414 generated files: clipboard.writeText 3, requestFullscreen 2.
           Deliberately NOT delegated: clipboard-READ (0 files ask for it, and it
           would let a generated page read whatever the owner last copied), camera,
           microphone, geolocation, display-capture. Not added to the decorative
           previews (:184, :212) either -- a 168px tabindex="-1" picture must not be
           able to fill the screen or touch the clipboard.
           Guard: tests/test_a_generated_app_can_copy_and_go_fullscreen.py -->
      ${netNotice}${(state.viewerPlaying || state.viewerPlayFrame) ? renderPlaytestPanel() : ''}${state.viewerPlayNote ? `<div class="tc-code-viewer-netnote" style="display:flex;align-items:center;gap:.5em;padding:.4em .9em;font-size:.8125em;opacity:.85;"><svg viewBox="0 0 256 256" width="17" height="17" fill="currentColor" aria-hidden="true"><path d="M176 100a12 12 0 1 1-12 12 12 12 0 0 1 12-12Zm28 20a12 12 0 1 0 12 12 12 12 0 0 0-12-12ZM104 116H92v-12a8 8 0 0 0-16 0v12H64a8 8 0 0 0 0 16h12v12a8 8 0 0 0 16 0v-12h12a8 8 0 0 0 0-16Zm141.9 60.9a36 36 0 0 1-53.4 6.3l-.4-.4-30.7-28.8H94.6l-30.7 28.8-.4.4A36 36 0 0 1 4 156.4a35 35 0 0 1 .8-4.4L27.4 61A44 44 0 0 1 70.2 28h115.6A44 44 0 0 1 228.6 61l22.6 91a35 35 0 0 1 .8 4.4 35.7 35.7 0 0 1-6.1 20.5ZM185.8 132a28 28 0 0 0 27.2-21.3l.1-.5A28 28 0 0 0 185.8 76H70.2A28 28 0 0 0 43 97.7l-22.6 91A20 20 0 0 0 20 156.4a19.9 19.9 0 0 0 33.9 11.7L86.3 137a8 8 0 0 1 5.5-2.2h72.4a8 8 0 0 1 5.5 2.2l32.4 30.4A20 20 0 0 0 236 156.4a19.6 19.6 0 0 0-.4-3.9Z"/></svg><span>${esc(state.viewerPlayNote)}</span></div>` : ''}
      <div class="tc-code-viewer-stage"><iframe title="${esc(file)}" sandbox="allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads allow-same-origin" allow="fullscreen; clipboard-write" src="${esc(doc)}"></iframe></div>
    </aside>`;
  }

  function openViewer(file) {
    state.viewer = { file: String(file), full: !!(state.viewer && state.viewer.full) };
  }

  // Thomas tests his own work before it's yours: after a build that produced a
  // playable page, open it and start the playtest automatically (owner,
  // 2026-08-10: "he could have easily caught this... why not before he
  // delivers it"). The verdict + recommendations land in the chat.
  function autoPlaytest(file) {
    const name = String(file || '');
    if (!name || !/\.x?html?$/i.test(name) || !state.activeId) return false;
    state.playtestResult = null;
    openViewer(name);
    render();
    startViewerPlay();
    return true;
  }

  function bindViewer(root, render) {
    const viewer = root.querySelector('.tc-code-viewer');
    if (!viewer) return;
    viewer.querySelector('[data-code-viewer-close]')?.addEventListener('click', () => { stopViewerPlay(); state.viewerPlayNote = ''; state.viewer = null; render(); });
    viewer.querySelector('[data-code-viewer-full]')?.addEventListener('click', () => {
      state.viewer = { ...(state.viewer || {}), full: !(state.viewer && state.viewer.full) };
      render();
    });
    viewer.querySelector('[data-code-viewer-play]')?.addEventListener('click', () => {
      if (state.viewerPlaying) stopViewerPlay(); else startViewerPlay();
      render();
    });
  }

  // "Let Thomas play while you watch" (owner, 2026-08-10). Thomas ACTUALLY
  // playtests: a server-side headless browser plays the game while a vision
  // model decides each move (thomas/server/game_playtest.py). This opens the
  // event stream and renders what Thomas sees, does, and concludes — live.
  function stopViewerPlay() {
    if (state.viewerPlaySource) { try { state.viewerPlaySource.close(); } catch (error) { /* already closed */ } }
    state.viewerPlaySource = null;
    state.viewerPlaying = false;
  }

  function startViewerPlay() {
    stopViewerPlay();
    const file = String((state.viewer && state.viewer.file) || '');
    if (!file || !state.activeId) {
      state.viewerPlayNote = 'Open a game first, then Thomas can play it.';
      return;
    }
    state.viewerPlaying = true;
    state.viewerPlayLog = [];
    state.viewerPlayNote = 'Thomas is opening the game to play it…';
    const url = `/api/evolve/agent/playtest/stream?conversation_id=${encodeURIComponent(state.activeId)}&file=${encodeURIComponent(file)}`;
    let source;
    try { source = new EventSource(url); } catch (error) { state.viewerPlaying = false; state.viewerPlayNote = 'Could not start the playtest.'; return; }
    state.viewerPlaySource = source;
    let hasPanel = false;
    source.onmessage = (event) => {
      let payload = {};
      try { payload = JSON.parse(event.data); } catch (error) { return; }
      const kind = String(payload.kind || '');
      if (kind === 'report') {
        // The verdict belongs in the MAIN CHAT, not the side window (owner,
        // 2026-08-10): the run's result, with recommendation buttons the user
        // can act on. The viewer goes back to showing the game.
        state.playtestResult = { report: payload.data || {}, file: String((state.viewer && state.viewer.file) || ''), at: 1 };
        state.viewerPlayReport = null;
        state.viewerPlayFrame = '';
        state.viewerPlayNote = '';
        stopViewerPlay();
        render();
        return;
      }
      if (kind === 'end') { stopViewerPlay(); render(); return; }
      if (kind === 'error') { state.viewerPlayNote = String(payload.text || 'Playtest error.'); stopViewerPlay(); render(); return; }
      if (kind === 'frame') {
        const data = payload.data || {};
        state.viewerPlayFrame = String(data.image || state.viewerPlayFrame || '');
        state.viewerPlayCaption = String(payload.text || state.viewerPlayCaption || '');
        if (data.see) state.viewerPlaySee = String(data.see);
        state.viewerPlayNote = '';
        // Update the live image in place — a full render every ~160ms would
        // rebuild the DOM and flicker. Only render() once to create the panel.
        const img = document.querySelector('.tc-code-playtest-frame');
        if (img && img.tagName === 'IMG') {
          img.src = `data:image/png;base64,${state.viewerPlayFrame}`;
          const move = document.querySelector('.tc-code-playtest-move');
          if (move) move.textContent = state.viewerPlayCaption;
          const see = document.querySelector('.tc-code-playtest-see');
          if (see && state.viewerPlaySee) see.textContent = state.viewerPlaySee;
          hasPanel = true;
        } else if (!hasPanel) {
          hasPanel = true;
          render();
        }
        return;
      }
      // observation / action / note: keep the caption fresh.
      if (kind === 'action' || kind === 'observation' || kind === 'note') {
        if (payload.text) state.viewerPlayCaption = String(payload.text);
        if (kind === 'observation' && payload.text) state.viewerPlaySee = String(payload.text);
      }
    };
    source.onerror = () => {
      // The stream ends by closing; only surface an error if nothing arrived.
      if (!state.viewerPlayLog || !state.viewerPlayLog.length) {
        state.viewerPlayNote = 'The playtest could not start (the game or the model was unavailable).';
      }
      stopViewerPlay();
      render();
    };
  }

  window.ThomasCodeResults = {
    playtestChatCardHtml,
    autoPlaytest,
    artifactCardsHtml,
    artifactHtml,
    bindViewer,
    configure,
    ensureArtifactDoc,
    htmlWantsNetwork,
    hydrateArtifactThumbnails,
    inlineLocalAssets,
    openViewer,
    presentNewestResult,
    readProjectFile,
    runReportHtml,
    viewerHtml,
  };
})();
