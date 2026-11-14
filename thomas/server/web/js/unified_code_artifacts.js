/* Build artifact cards, preview documents, and download actions. */
(function () {
  'use strict';
  function create(deps) {


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
      const url = `/api/evolve/agent/artifact/${encodeURIComponent(deps.state.activeId)}/${file.split('/').map(encodeURIComponent).join('/')}`;
      const title = `<strong>${deps.esc(file)}</strong><a href="${url}" target="_blank" rel="noopener">Open</a>`;
      if (artifact.kind === 'html') return `<section class="tc-code-artifact"><header>${title}</header><div class="tc-code-artifact-shot"><iframe src="${url}" sandbox="allow-scripts allow-forms allow-same-origin" title="Preview ${deps.esc(file)}" tabindex="-1" scrolling="no"></iframe></div></section>`;
      if (artifact.kind === 'image') return `<section class="tc-code-artifact"><header>${title}</header><img src="${url}" alt="Generated artifact ${deps.esc(file)}"></section>`;
      // PDF/schematic artifacts preview inline too (parity with chat), not just a link.
      if (artifact.kind === 'pdf' || /\.pdf(?:$|[?#])/i.test(file)) return `<section class="tc-code-artifact"><header>${title}</header><iframe src="${url}#toolbar=0&navpanes=0&view=FitH" title="Preview ${deps.esc(file)}"></iframe></section>`;
      if (/\.svg(?:$|[?#])/i.test(file)) return `<section class="tc-code-artifact"><header>${title}</header><img src="${url}" alt="Generated artifact ${deps.esc(file)}"></section>`;
      return `<section class="tc-code-artifact is-link"><header>${title}</header><span>${deps.esc(artifact.kind || 'artifact')} result</span></section>`;
    }

    const isPage = file => /\.x?html?$/i.test(String(file || ''));
    const isImage = file => /\.(?:png|jpe?g|gif|webp|svg|avif)(?:$|[?#])/i.test(String(file || ''));

    // What the page calls itself: its <title>, read once with the same validated
    // file read the preview uses; failing that, the conversation's name; failing
    // that, the file name without its extension, spoken as words.
    function previewTitle(file) {
      const known = deps.state.artifactTitles && deps.state.artifactTitles[file];
      if (known) return known;
      const convo = deps.state.conversation || {};
      const named = String(convo.title || convo.name || '').trim();
      if (named) return named;
      const base = String(file).split('/').pop().replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ');
      return base.replace(/^./, c => c.toUpperCase());
    }

    // The deliverable, big and live, in the reading column: a sandboxed frame of
    // the real page that you play right where it is. No file name and no
    // caption -- the page's title shows on hover only, and the two controls are
    // icons (full screen, new tab). The frame is the viewer's own sandbox; the
    // page loads lazily (bindLivePreviews) and the node survives re-render.
    function livePreviewHtml(file, slot, href) {
      const doc = deps.state.artifactDocs && deps.state.artifactDocs[file];
      const title = previewTitle(file);
      const frame = doc
        ? `<iframe class="tc-live-frame" data-live-src="${deps.esc(doc)}" title="${deps.esc(title)}" scrolling="no" sandbox="allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads allow-same-origin" allow="fullscreen; gamepad; autoplay; clipboard-write"></iframe>`
        : '<div class="tc-live-wait" aria-hidden="true"></div>';
      return `<figure class="tc-live" data-code-live="${deps.esc(slot)}" data-live-doc="${deps.esc(doc || '')}" title="${deps.esc(title)}">${frame}
        <span class="tc-live-label" aria-hidden="true">${deps.esc(title)}</span>
        <div class="tc-live-tools">
          <button type="button" class="tc-live-btn" data-code-live-full data-tip="Full screen" aria-label="Full screen"><svg viewBox="0 0 16 16" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"/></svg></button>
          <a class="tc-live-btn" data-code-artifact-open href="${deps.esc(href)}" target="_blank" rel="noopener noreferrer" aria-label="Open in a new tab" data-tip="Open in a new tab"><svg viewBox="0 0 16 16" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 2.5h4.5V7M13.5 2.5L7.5 8.5M11.5 9.5v3a1 1 0 0 1-1 1h-7a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3"/></svg></a>
        </div>
      </figure>`;
    }

    // Something that is not a page: an image shows large, anything else is an
    // icon and its name. Both open in the viewer panel beside the chat.
    function plainCardHtml(a, slot, href, open) {
      const file = String(a.file);
      const thumb = isImage(file) && href
        ? `<span class="tc-code-artifact-thumb is-image"><img src="${deps.esc(href)}" alt="" loading="lazy"></span>`
        : '<span class="tc-code-artifact-thumb is-icon"><i class="ph ph-file" aria-hidden="true"></i></span>';
      const name = isImage(file) ? '' : `<span class="tc-code-artifact-meta"><span class="tc-code-artifact-name">${deps.esc(file)}</span></span>`;
      return `<div class="tc-code-artifact${isImage(file) ? ' is-image' : ''}"><button class="tc-code-artifact-open" data-code-open-artifact="${deps.esc(file)}" data-code-artifact-slot="${deps.esc(slot)}" type="button" aria-expanded="${open ? 'true' : 'false'}" title="${deps.esc(previewTitle(file))}">${thumb}${name}</button></div>`;
    }

    // What Thomas just made, handed over in the reply itself. The turn carries
    // artifacts -- [{file:'trey-badlands.html',kind:'html'}] -- and a count is
    // not a delivery. A page becomes ONE large live preview (the entry page,
    // index.html else the first); other files stay reachable from the Activity
    // drawer's Outputs, where Keep / Revert / Review also live.
    function artifactCardsHtml(turn, turnKey) {
      const items = (turn.artifacts || []).filter(a => a && a.file && !deps.isInternalResultPath(a.file));
      if (!items.length) return '';
      const urlFor = file => (deps.state.activeId
        ? `/api/evolve/agent/artifact/${encodeURIComponent(deps.state.activeId)}/${file.split('/').map(encodeURIComponent).join('/')}`
        : '');
      const slotOf = file => `${turnKey}::${file}`;
      const pages = items.filter(a => isPage(a.file));
      const entry = pages.find(a => /(?:^|\/)index\.x?html?$/i.test(String(a.file))) || pages[0];
      const cards = entry
        ? livePreviewHtml(String(entry.file), slotOf(String(entry.file)), urlFor(String(entry.file)))
        : items.map(a => {
          const slot = slotOf(String(a.file));
          return plainCardHtml(a, slot, urlFor(String(a.file)), !!(deps.state.artifactOpen && deps.state.artifactOpen[slot]));
        }).join('');
      return `<div class="tc-code-artifacts">${cards}</div>`;
    }

    // Wire the live previews after a render. Loading is lazy: a frame gets its
    // src when it scrolls near the view, so a long history does not boot every
    // game at once. render() rewrites innerHTML, which would reset a game being
    // played; ThomasCodeViewState moves each loaded frame aside and back
    // (moveBefore keeps the page alive) so it is reused when the same page is
    // still there.
    function bindLivePreviews(root) {
      const figures = [...root.querySelectorAll('[data-code-live]')];
      if (!figures.length) return;
      const load = frame => { if (frame && !frame.getAttribute('src') && frame.dataset.liveSrc) frame.src = frame.dataset.liveSrc; };
      const io = typeof IntersectionObserver === 'function'
        ? new IntersectionObserver(entries => entries.forEach(e => { if (e.isIntersecting) { load(e.target.querySelector('iframe')); io.unobserve(e.target); } }), { rootMargin: '300px' })
        : null;
      figures.forEach(figure => {
        const frame = figure.querySelector('iframe');
        if (frame && !frame.getAttribute('src')) { if (io) io.observe(figure); else load(frame); }
        figure.addEventListener('pointerdown', event => {
          if (event.target.closest('.tc-live-tools')) return;
          figure.classList.add('is-playing');
          try { if (frame) frame.focus(); } catch (e) { /* focus is a courtesy */ }
        });
        // Scale the desktop-sized page to the card; in full screen it is native and may scroll.
        if (!figure.dataset.liveFit) {
          figure.dataset.liveFit = '1';
          const fit = () => { if (!figure.ownerDocument.fullscreenElement && figure.clientWidth) figure.style.setProperty('--live-scale', String(figure.clientWidth / 1280)); };
          fit();
          if (typeof ResizeObserver === 'function') new ResizeObserver(fit).observe(figure);
          figure.addEventListener('fullscreenchange', () => {
            const on = figure.ownerDocument.fullscreenElement === figure;
            if (frame) frame.setAttribute('scrolling', on ? 'auto' : 'no');
            if (!on) fit();
          });
        }
        figure.addEventListener('pointerleave', () => figure.classList.remove('is-playing'));
        const full = figure.querySelector('[data-code-live-full]');
        if (full) full.addEventListener('click', () => {
          const doc = figure.ownerDocument;
          if (doc.fullscreenElement) { void doc.exitFullscreen(); return; }
          if (figure.requestFullscreen) void figure.requestFullscreen().then(() => { try { if (frame) frame.focus(); } catch (e) { /* ok */ } }).catch(() => {});
        });
      });
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
      deps.state.artifactDocs = deps.state.artifactDocs || {};
      if (deps.state.artifactDocs[file] !== undefined) return true;
      const token = deps.lifecycle().contextToken(deps.state);
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
      const base = deps.state.previewBase && deps.state.previewBase.cid === token.id ? deps.state.previewBase.url : '';
      if (base) url = `${base}/${file.split('/').map(encodeURIComponent).join('/')}`;
      else {
        try {
          const r = await fetch(`/api/evolve/agent/conversations/${encodeURIComponent(token.id)}/preview?path=${encodeURIComponent(file)}`);
          const d = await r.json();
          if (r.ok && d && d.ok && d.url) url = String(d.url);
        } catch (e) { url = null; }
      }
      if (!deps.lifecycle().contextMatches(deps.state, token)) return false;
      if (!url) return false;
      if (!base) {
        // Everything up to the capability; the tail is per file.
        const cut = url.lastIndexOf('/');
        if (cut > 0) deps.state.previewBase = { cid: token.id, url: url.slice(0, cut) };
      }
      deps.state.artifactDocs[file] = url;
      // Learn whether the page asks for the network BEFORE the redraw that shows
      // it, through the same validated read the asset inliner uses. Awaited on
      // purpose: a flag arriving after render() would need another render, and
      // render() rewrites innerHTML, which destroys every live preview iframe
      // (see the note above). One extra file read per HTML artifact, once.
      if (/\.x?html?$/i.test(file)) {
        deps.state.artifactNet = deps.state.artifactNet || {};
        if (deps.state.artifactNet[file] === undefined) {
          try {
            const body = await readProjectFile(token.id, file);
            deps.state.artifactNet[file] = body === null ? false : htmlWantsNetwork(body);
            const found = body === null ? null : /<title[^>]*>([^<]{1,80})<\/title>/i.exec(body);
            deps.state.artifactTitles = deps.state.artifactTitles || {};
            if (found && found[1].trim()) deps.state.artifactTitles[file] = found[1].trim();
          } catch (e) { deps.state.artifactNet[file] = false; }
        }
      }
      if (!quiet) deps.render();
      return true;

    }
    async function hydrateArtifactThumbnails() {
      const turns = (deps.state.conversation && deps.state.conversation.turns) || [];
      const wanted = [];
      for (let i = turns.length - 1; i >= 0 && wanted.length < deps._ARTIFACT_THUMB_BUDGET; i -= 1) {
        const turn = turns[i];
        if (!turn || turn.role !== 'agent') continue;
        for (const a of turn.artifacts || []) {
          const file = a && a.file ? String(a.file) : '';
          if (!file || deps.isInternalResultPath(file) || !/\.x?html?$/i.test(file)) continue;
          if (wanted.includes(file)) continue;
          wanted.push(file);
          if (wanted.length >= deps._ARTIFACT_THUMB_BUDGET) break;
        }
      }
      let resolved = false;
      for (const file of wanted) {
        try { resolved = (await ensureArtifactDoc(file, true)) || resolved; } catch (e) { /* one bad result must not stop the rest */ }
      }
      if (resolved) deps.render();
    }

    // Open what the last completed turn produced. Prefers a page, because a page
    // is the thing you can actually look at; falls back to whatever else it made.
    async function presentNewestResult() {
      const turns = (deps.state.conversation && deps.state.conversation.turns) || [];
      for (let i = turns.length - 1; i >= 0; i -= 1) {
        const turn = turns[i];
        if (!turn || turn.role !== 'agent' || !turn.ok) continue;
        const made = (turn.artifacts || []).filter(a => a && a.file && !deps.isInternalResultPath(a.file));
        if (!made.length) return false;
        const pick = made.find(a => /\.x?html?$/i.test(String(a.file))) || made[0];
        const file = String(pick.file);
        deps.state.artifactOpen = deps.state.artifactOpen || {};
        deps.state.artifactOpen[`${turn.run_id || turn.ts || '0'}::${file}`] = true;   // in the conversation
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

    // The artifact control a rendered turn carries. Bound here, beside the
    // cards `artifactCardsHtml` stamps it into, for the same reason `bindViewer`
    // is: the markup and the click that answers it belong to one module. (The
    // turn's "Open in a tab" is a plain link; "Keep all" and "Review N files"
    // act on the drawer's pending changes and are bound by the mode that owns
    // them.)
    //
    // Kept LAST before the exports on purpose. The guard that a result opens in
    // the conversation rather than being pushed to the side panel
    // (test_code_presents_what_it_made.py) reads everything from the
    // `[data-code-open-artifact]` selector to the next `});` and requires no
    // drawer state in it; anything appended after this that touches
    // `state.drawerOpen` would be read as part of this handler.
    function bindArtifactActions(root) {
      bindLivePreviews(root);
      root.querySelectorAll('[data-code-open-artifact]').forEach(button => button.addEventListener('click', () => {
        // Opens IN THE CONVERSATION. Sending the result to a side panel is still
        // telling someone where to go and look; Chat puts a deliverable in the
        // thread and Code is meant to be Chat that builds rather than dispatches.
        const file = button.dataset.codeOpenArtifact;
        const slot = button.dataset.codeArtifactSlot || file;
        deps.state.artifactOpen = deps.state.artifactOpen || {};
        deps.state.artifactOpen[slot] = true;
        // Opens BESIDE the conversation rather than inside it. The card stays a
        // snapshot you can read at a glance; the real thing gets the height of
        // the window, and from there it can fill Thomas or leave for its own tab.
        deps.openViewer(file);
        deps.render();
        // Fetch the previewable copy after the panel is up, then redraw so the
        // frame swaps from the plain artifact URL to the asset-inlined document.
        void deps.safely(async () => { await ensureArtifactDoc(file); deps.render(); }, 'That result could not be opened.');
      }));
    }
    return { htmlWantsNetwork, artifactHtml, artifactCardsHtml, bindLivePreviews, ensureArtifactDoc, hydrateArtifactThumbnails, presentNewestResult, readProjectFile, inlineLocalAssets, bindArtifactActions };
  }
  window.ThomasCodeArtifacts = { create };
})();
