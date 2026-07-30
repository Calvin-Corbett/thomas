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

  function reportRow(ok, heading, label) {
    return `<div class="tc-code-technical${ok ? '' : ' is-error'}"><i class="ph ph-${ok ? 'check-circle' : 'warning'}"></i><div><strong>${esc(heading)}</strong><code>${esc(label)}</code></div></div>`;
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
    const list = value => Array.isArray(value) ? value : [];
    const attempts = list(report.attempts).map(item => reportRow(!/fail/i.test(String(item.outcome || '')), `Pass ${item.pass || '?'} · ${String(item.outcome || 'unknown')}`, `${String(item.goal || '')} → ${String(item.exit_state || '')}`));
    const validations = list(report.validations).map(item => reportRow(item.passed === true, item.passed === true ? 'Check passed' : 'Check failed', `${String(item.command || item.kind || 'check')} — ${String(item.evidence || '')}`));
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
    // Matched on the engine's own marker rather than the word "skipped", which
    // turns up in unrelated evidence such as "1 files checked, 1 skipped".
    const wasSkipped = item => /[A-Z][A-Z_]*_SKIPPED\b/.test(String(item.evidence || ''));
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
    let tone = 'is-good';
    let verdict = 'Checks passed';
    if (failed > 0) { tone = 'is-bad'; verdict = failed === ran ? 'Checks failed' : 'Some checks failed'; }
    else if (!ran) { tone = 'is-unknown'; verdict = 'Nothing was checked'; }
    else if (unverified) { tone = 'is-unknown'; verdict = 'Not checked against your ask'; }
    else if (riskCount) { tone = 'is-warn'; verdict = 'Passed, with things to look at'; }

    const facts = [];
    if (ran) facts.push(`${passed}/${ran} check${ran === 1 ? '' : 's'} passed`);
    if (skipped) facts.push(`${skipped} check${skipped === 1 ? '' : 's'} skipped`);
    if (unverified) facts.push(`${unverified} requirement${unverified === 1 ? '' : 's'} unverified`);
    facts.push(riskCount ? `${riskCount} open risk${riskCount === 1 ? '' : 's'}` : 'no open risks');
    if (attempts.length > 1) facts.push(`${attempts.length} edit passes`);

    const glyph = tone === 'is-bad' ? 'warning-circle' : (tone === 'is-warn' ? 'warning' : (tone === 'is-unknown' ? 'info' : 'check-circle'));
    return `<details class="tc-code-saved-activity tc-code-run-report ${tone}${riskCount ? ' has-issues' : ''}" data-saved="true">
      <summary>
        <span class="tc-code-verdict"><i class="ph ph-${glyph}" aria-hidden="true"></i><span class="tc-code-verdict-text"><strong>${esc(verdict)}</strong><small>${esc(facts.join(' · '))}</small></span></span>
        <span class="tc-code-verdict-more">Show details</span>
      </summary>
      <div class="tc-code-technical-log">${sections}</div>
    </details>`;
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
      return `<div class="tc-code-artifact">
        <div class="tc-code-artifact-row">
          <button class="tc-code-artifact-open" data-code-open-artifact="${esc(file)}" data-code-artifact-slot="${esc(slot)}" type="button" aria-expanded="${open ? 'true' : 'false'}">
            ${thumb}
            <span class="tc-code-artifact-meta">
              <span class="tc-code-artifact-name">${esc(file)}</span>
              <span class="tc-code-artifact-verb">${hint}</span>
            </span>
          </button>${openTab}${save}
        </div>${expanded}
      </div>`;
    }).join('');
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

  function viewerHtml() {
    const open = state.viewer && state.viewer.file;
    if (!open) return '';
    const file = String(state.viewer.file);
    const doc = (state.artifactDocs && state.artifactDocs[file]) || artifactUrlFor(file);
    const full = !!state.viewer.full;
    // `allow-same-origin` is withheld on purpose: the frame only has to render.
    return `<aside class="tc-code-viewer${full ? ' is-full' : ''}" role="dialog" aria-label="${esc(file)}">
      <header class="tc-code-viewer-head">
        <div class="tc-code-viewer-title"><i class="ph ph-browser" aria-hidden="true"></i><strong>${esc(file)}</strong></div>
        <div class="tc-code-viewer-tools">
          <button type="button" data-code-viewer-full aria-pressed="${full ? 'true' : 'false'}" title="${full ? 'Shrink back beside the chat' : 'Expand to fill Thomas'}" aria-label="${full ? 'Shrink back beside the chat' : 'Expand to fill Thomas'}"><i class="ph ph-${full ? 'corners-in' : 'corners-out'}" aria-hidden="true"></i></button>
          <a href="${esc(artifactUrlFor(file))}" target="_blank" rel="noopener noreferrer" title="Open in a new browser tab" aria-label="Open in a new browser tab"><i class="ph ph-arrow-square-out" aria-hidden="true"></i></a>
          <button type="button" data-code-viewer-close title="Close" aria-label="Close"><i class="ph ph-x" aria-hidden="true"></i></button>
        </div>
      </header>
      <div class="tc-code-viewer-stage"><iframe title="${esc(file)}" sandbox="allow-scripts allow-forms" src="${esc(doc)}"></iframe></div>
    </aside>`;
  }

  function openViewer(file) {
    state.viewer = { file: String(file), full: !!(state.viewer && state.viewer.full) };
  }

  function bindViewer(root, render) {
    const viewer = root.querySelector('.tc-code-viewer');
    if (!viewer) return;
    viewer.querySelector('[data-code-viewer-close]')?.addEventListener('click', () => { state.viewer = null; render(); });
    viewer.querySelector('[data-code-viewer-full]')?.addEventListener('click', () => {
      state.viewer = { ...(state.viewer || {}), full: !(state.viewer && state.viewer.full) };
      render();
    });
  }

  window.ThomasCodeResults = {
    artifactCardsHtml,
    artifactHtml,
    bindViewer,
    configure,
    ensureArtifactDoc,
    hydrateArtifactThumbnails,
    inlineLocalAssets,
    openViewer,
    presentNewestResult,
    readProjectFile,
    runReportHtml,
    viewerHtml,
  };
})();
