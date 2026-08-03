/* The panels the composer bar opens: the AI-settings sheet behind "Tools",
   the Thomas Library project picker, the attachment chips and voice input.

   Lifted out of chat.html's single inline <script> when that page passed the
   3000-line ceiling in tests/test_architecture.py::test_frontend_file_sizes
   (3310 -> 2975 lines). The bodies below are exactly what the page ran. The
   only change is that the closure values they used to read directly now
   arrive as arguments, and the page destructures the same names back out, so
   every call site in chat.html is untouched.

   DIAL_FIELDS and saveDials stay in the page on purpose: a UX guard
   (tests/test_web_evolve_chat_ux.py) pins the effort vocabulary to chat.html
   itself, and setProfile still calls saveDials. */
(function () {
  "use strict";

  function create(deps) {
    const state = deps.state;
    const esc = deps.esc;
    const inputEl = deps.inputEl;
    const autosize = deps.autosize;
    const syncDynamic = deps.syncDynamic;
    const DIAL_FIELDS = deps.DIAL_FIELDS;
    const saveDials = deps.saveDials;

    function renderToolsMenu() {
      const wrap = document.getElementById('tc-tools-menu'); if (!wrap) return;
      wrap.innerHTML = '<div style="font-size:10.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--c-muted);padding:2px 2px 10px;">AI settings</div>';
      DIAL_FIELDS.forEach(f => {
        const row = document.createElement('label');
        row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px;font-size:13px;';
        const span = document.createElement('span'); span.textContent = f.label; span.style.color = 'var(--c-dim)';
        const sel = document.createElement('select');
        sel.style.cssText = 'flex:0 0 auto;min-width:140px;background:var(--c-surface);color:var(--c-text);border:1px solid var(--c-border);border-radius:8px;padding:5px 8px;font-family:inherit;font-size:12.5px;cursor:pointer;';
        f.opts.forEach(([val, lbl]) => { const o = document.createElement('option'); o.value = String(val); o.textContent = lbl; if (String(val) === String(state.dials[f.key])) o.selected = true; sel.appendChild(o); });
        sel.addEventListener('change', () => { state.dials[f.key] = f.num ? parseInt(sel.value, 10) : sel.value; saveDials(); });
        row.appendChild(span); row.appendChild(sel); wrap.appendChild(row);
      });
      const memRow = document.createElement('label');
      memRow.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:4px;font-size:13px;cursor:pointer;';
      const memSpan = document.createElement('span'); memSpan.textContent = 'Memory'; memSpan.style.color = 'var(--c-dim)';
      const memChk = document.createElement('input'); memChk.type = 'checkbox'; memChk.checked = !!state.dials.memory; memChk.style.cssText = 'width:16px;height:16px;cursor:pointer;accent-color:var(--c-accent);';
      memChk.addEventListener('change', () => { state.dials.memory = memChk.checked; saveDials(); });
      memRow.appendChild(memSpan); memRow.appendChild(memChk); wrap.appendChild(memRow);
    }
    function toggleToolsMenu() {
      state.toolsMenuOpen = !state.toolsMenuOpen;
      const m = document.getElementById('tc-tools-menu');
      m.style.display = state.toolsMenuOpen ? 'block' : 'none';
      if (state.toolsMenuOpen) renderToolsMenu();
    }
    function closeToolsMenu() { state.toolsMenuOpen = false; const m = document.getElementById('tc-tools-menu'); if (m) m.style.display = 'none'; }

    // ---------- Thomas Library (choose what Thomas works on) ----------
    // A folder path is not how anyone remembers what they made. 88 of the 113
    // projects here are files called "index" — the only way to tell them apart
    // is to LOOK at them, so each card renders the real thing, live.
    //
    // Every preview is a grant against the deliverable preview service, which
    // keeps at most 32 alive and evicts by LRU. Mounting 113 iframes would
    // therefore destroy sockets while the user scrolled, so frames are mounted
    // only as cards come into view and never more than PREVIEW_BUDGET at once.
    const LIBRARY_PREVIEW_BUDGET = 12;
    // Every DISTINCT preview costs a cookie in the 127.0.0.1 jar for an hour,
    // and cookies carry no port, so the deliverable service's cookies are sent
    // to this app too. At ~71 bytes each, 115 of them exceed the 8190-byte
    // header limit and every request to Thomas starts failing with a 400 until
    // they expire. With 111 generated apps, one unbroken scroll of this shelf
    // very nearly gets there on its own -- no other surface mounts previews in
    // that quantity, so this panel is the only thing that can reach it.
    //
    // 32 is not arbitrary: it is the deliverable service's own concurrent-grant
    // ceiling (_MAX_ACTIVE_PREVIEW_GRANTS), so this asks for nothing the server
    // would not already hold. Past it, cards keep their title and monogram and
    // simply do not go live. Re-showing something already mounted is free --
    // the grant, and therefore the cookie, already exists.
    const LIBRARY_DISTINCT_PREVIEW_CAP = 32;
    let _librarySeenPreviews = new Set();
    state.libraryMenuOpen = false;
    state.libraryProjects = null;
    state.libraryLoading = false;
    state.libraryError = '';
    state.libraryFilter = '';
    let _libraryObserver = null;
    let _libraryMounted = [];

    function relativeWhen(iso) {
      const t = Date.parse(String(iso || ''));
      if (!Number.isFinite(t)) return '';
      const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
      if (mins < 1) return 'just now';
      if (mins < 60) return `${mins} min ago`;
      const hrs = Math.round(mins / 60);
      if (hrs < 24) return `${hrs} hour${hrs === 1 ? '' : 's'} ago`;
      const days = Math.round(hrs / 24);
      if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`;
      if (days < 31) return `${Math.round(days / 7)} week${Math.round(days / 7) === 1 ? '' : 's'} ago`;
      return new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    }

    function libraryVisibleProjects() {
      const all = Array.isArray(state.libraryProjects) ? state.libraryProjects : [];
      const q = state.libraryFilter.trim().toLowerCase();
      if (!q) return all;
      return all.filter(p => `${p.name || ''} ${p.request_title || ''} ${p.entry_path || ''}`.toLowerCase().includes(q));
    }

    function toggleLibraryMenu() {
      state.libraryMenuOpen = !state.libraryMenuOpen;
      const m = document.getElementById('tc-code-library-menu');
      const btn = document.getElementById('tc-code-project-btn');
      if (!m) return;
      m.style.display = state.libraryMenuOpen ? 'flex' : 'none';
      if (btn) btn.setAttribute('aria-expanded', state.libraryMenuOpen ? 'true' : 'false');
      if (!state.libraryMenuOpen) { teardownLibraryPreviews(); return; }
      positionLibraryMenu();
      renderLibraryMenu();
      if (state.libraryProjects === null && !state.libraryLoading) loadLibraryProjects();
      const filter = document.getElementById('tc-library-filter');
      if (filter) filter.focus();
    }

    function closeLibraryMenu(options) {
      if (!state.libraryMenuOpen) return;
      state.libraryMenuOpen = false;
      const m = document.getElementById('tc-code-library-menu');
      if (m) m.style.display = 'none';
      const btn = document.getElementById('tc-code-project-btn');
      if (btn) {
        btn.setAttribute('aria-expanded', 'false');
        if (options && options.restoreFocus) btn.focus();
      }
      teardownLibraryPreviews();
    }

    // The trigger sits mid-composer, so a panel anchored to its left edge runs
    // off the right of the window and clips its own New project button. Pull it
    // back by however much it overflows, leaving a margin.
    function positionLibraryMenu() {
      const m = document.getElementById('tc-code-library-menu');
      const wrap = document.getElementById('tc-code-project-wrap');
      if (!m || !wrap) return;
      m.style.left = '0px';
      const wrapLeft = wrap.getBoundingClientRect().left;
      const width = m.getBoundingClientRect().width;
      const margin = 16;
      const overflow = (wrapLeft + width) - (window.innerWidth - margin);
      if (overflow > 0) m.style.left = `${-Math.min(overflow, Math.max(0, wrapLeft - margin))}px`;
    }
    window.addEventListener('resize', () => { if (state.libraryMenuOpen) positionLibraryMenu(); });

    function teardownLibraryPreviews() {
      if (_libraryObserver) { try { _libraryObserver.disconnect(); } catch (e) {} _libraryObserver = null; }
      // Unload the frames as well as forgetting them. Dropping only the
      // bookkeeping left a dozen model-written pages running behind a closed
      // panel, still holding preview grants and still able to post messages at
      // this window. The LRU evictor already clears holders this way.
      _libraryMounted.forEach(function (holder) {
        try { libraryRestMonogram(holder); delete holder.dataset.libMountedFrame; } catch (e) {}
      });
      _libraryMounted = [];
    }

    async function loadLibraryProjects() {
      state.libraryLoading = true;
      state.libraryError = '';
      renderLibraryMenu();
      try {
        const res = await fetch('/api/local/projects');
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error('unavailable');
        state.libraryProjects = Array.isArray(data.projects) ? data.projects : [];
      } catch (e) {
        state.libraryProjects = [];
        state.libraryError = 'Thomas could not read your library just now.';
      } finally {
        state.libraryLoading = false;
        renderLibraryMenu();
      }
    }

    function libraryMonogram(name, accent) {
      const letter = String(name || '?').trim().charAt(0).toUpperCase() || '?';
      return `<span style="position:absolute;inset:0;display:grid;place-items:center;background:linear-gradient(135deg, ${accent}22, ${accent}0a);color:${accent};font-size:24px;font-weight:800;">${esc(letter)}</span>`;
    }

    // Unloading a preview puts its tile back to the monogram rather than to
    // nothing, so eviction while scrolling never leaves an empty rectangle.
    function libraryRestMonogram(holder) {
      const card = holder.closest('[data-lib-card]');
      const name = (card && card.getAttribute('data-lib-label')) || '';
      holder.innerHTML = libraryMonogram(name, 'var(--c-accent)');
    }

    function libraryCardHTML(p, i) {
      const title = esc(p.request_title || p.name || 'Untitled');
      const when = relativeWhen(p.updated_at || p.created_at);
      const file = esc(String(p.entry_path || '').split(/[\\/]/).pop() || '');
      const meta = [file, when].filter(Boolean).join(' · ');
      const url = String(p.artifact_url || '');
      const accent = esc(String((p.board_icon && p.board_icon.accent) || 'var(--c-accent)'));
      // The monogram is the resting state of every tile, not just of the ones
      // with nothing to show. A card that has not mounted yet -- because it is
      // below the fold, or past the preview budget -- then reads as a project
      // rather than as a blank rectangle, and a live preview simply replaces it.
      const monogram = libraryMonogram(p.request_title || p.name, accent);
      const preview = url
        ? `<span data-lib-frame="${esc(url)}" style="position:absolute;inset:0;display:block;background:var(--c-surface);">${monogram}</span>`
        : monogram;
      return `<button data-lib-card="${esc(p.root_path || '')}" data-lib-label="${title}" title="${title}"
        style="display:flex;flex-direction:column;text-align:left;padding:0;border:1px solid var(--c-border);border-radius:12px;overflow:hidden;background:var(--c-surface);cursor:pointer;font-family:inherit;transition:border-color .15s, transform .15s;">
        <span style="position:relative;display:block;width:100%;aspect-ratio:16/10;overflow:hidden;border-bottom:1px solid var(--c-border);">${preview}</span>
        <span style="display:flex;flex-direction:column;gap:3px;padding:9px 11px 11px;min-width:0;">
          <span style="font-size:12.5px;font-weight:700;color:var(--c-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${title}</span>
          <span style="font-size:11px;color:var(--c-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(meta) || '&nbsp;'}</span>
        </span>
      </button>`;
    }

    function renderLibraryMenu() {
      const m = document.getElementById('tc-code-library-menu');
      if (!m || !state.libraryMenuOpen) return;
      const items = libraryVisibleProjects();
      const total = Array.isArray(state.libraryProjects) ? state.libraryProjects.length : 0;
      let body;
      if (state.libraryLoading) {
        body = `<div style="padding:34px 16px;text-align:center;color:var(--c-muted);font-size:13px;">Looking through your library…</div>`;
      } else if (state.libraryError) {
        body = `<div style="padding:34px 16px;text-align:center;color:var(--c-muted);font-size:13px;">${esc(state.libraryError)}</div>`;
      } else if (!total) {
        body = `<div style="padding:30px 16px;text-align:center;color:var(--c-muted);font-size:13px;line-height:1.6;">
          Nothing here yet.<br>Anything Thomas builds for you shows up here automatically —<br>or pick a folder from your PC to work on.</div>`;
      } else if (!items.length) {
        body = `<div style="padding:30px 16px;text-align:center;color:var(--c-muted);font-size:13px;">No project matches “${esc(state.libraryFilter)}”.</div>`;
      } else {
        body = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(184px,1fr));gap:12px;">${items.map(libraryCardHTML).join('')}</div>`;
      }
      m.innerHTML = `
        <div style="flex:0 0 auto;display:flex;align-items:center;gap:10px;padding:13px 14px 11px;border-bottom:1px solid var(--c-border);">
          <div style="flex:1;min-width:0;">
            <div style="font-size:13.5px;font-weight:700;color:var(--c-text);">What should Thomas work on?</div>
            <div style="font-size:11.5px;color:var(--c-muted);margin-top:2px;">${total ? `${total} project${total === 1 ? '' : 's'} in your library` : 'Your library'}</div>
          </div>
          <button data-lib-action="browse" class="hv-icon" style="display:flex;align-items:center;gap:6px;height:32px;padding:0 11px;border-radius:9px;border:1px solid var(--c-border);background:transparent;color:var(--c-dim);font-family:inherit;font-size:12.5px;font-weight:600;cursor:pointer;"><i class="ph ph-folder-open" style="font-size:15px;"></i>Browse my PC</button>
          <button data-lib-action="new" class="hv-icon" style="display:flex;align-items:center;gap:6px;height:32px;padding:0 11px;border-radius:9px;border:1px solid var(--c-accent-line);background:var(--c-accent-soft);color:var(--c-text);font-family:inherit;font-size:12.5px;font-weight:600;cursor:pointer;"><i class="ph ph-plus" style="font-size:15px;"></i>New project</button>
        </div>
        ${total ? `<div style="flex:0 0 auto;padding:10px 14px 0;"><input id="tc-library-filter" type="text" placeholder="Search your library…" value="${esc(state.libraryFilter)}" style="width:100%;height:32px;padding:0 11px;border-radius:9px;border:1px solid var(--c-border);background:var(--c-surface);color:var(--c-text);font-family:inherit;font-size:12.5px;outline:none;"></div>` : ''}
        <div class="tc-scroll" id="tc-library-body" style="flex:1;min-height:0;overflow:auto;padding:12px 14px 14px;">${body}</div>`;
      mountLibraryPreviews();
    }

    function mountLibraryPreviews() {
      teardownLibraryPreviews();
      const holders = Array.from(document.querySelectorAll('#tc-code-library-menu [data-lib-frame]'));
      if (!holders.length) return;
      const mount = (holder) => {
        if (holder.dataset.libMountedFrame === '1') return;
        const key = holder.getAttribute('data-lib-frame') || '';
        // A grant already taken costs nothing to show again; a new one does.
        // Past the budget the tile simply keeps the monogram it was rendered
        // with, so it still reads as a project rather than as a blank.
        if (!_librarySeenPreviews.has(key) && _librarySeenPreviews.size >= LIBRARY_DISTINCT_PREVIEW_CAP) return;
        _librarySeenPreviews.add(key);
        if (_libraryMounted.length >= LIBRARY_PREVIEW_BUDGET) {
          // Budget is spent: release the least-recently shown frame first so the
          // preview service never sees more than LIBRARY_PREVIEW_BUDGET grants.
          const oldest = _libraryMounted.shift();
          if (oldest) { libraryRestMonogram(oldest); delete oldest.dataset.libMountedFrame; }
        }
        const src = holder.getAttribute('data-lib-frame') || '';
        // Render each app at a desktop width, then scale that down to exactly
        // fill this tile. The grid is fluid (auto-fill minmax), so a hard-coded
        // scale letterboxes every card with white margins -- measure instead.
        const box = holder.getBoundingClientRect();
        const logicalW = 1200;
        const logicalH = Math.round(logicalW * (box.height / (box.width || 1)) ) || 750;
        const scale = (box.width || 184) / logicalW;
        // These pages were written by a model, so pin their capabilities in the
        // markup as well as in the response. The iframe attribute INTERSECTS
        // with the server's CSP sandbox, so this is a floor, not a grant.
        //
        // allow-same-origin is included deliberately. The deliverable is served
        // from its own ephemeral 127.0.0.1:<port>, which is already a different
        // origin from the chat page -- "same-origin" here means the app's own
        // origin, never the parent's, and the parent stays unreachable either
        // way. Dropping it would give the frame an opaque origin instead, which
        // makes web storage throw: 15 of the 297 generated apps on this machine
        // use localStorage, including the snake game and Orbit. Breaking real
        // apps to re-state a boundary the origin already enforces is a bad
        // trade. allow-forms is not carried over from the CSP -- a preview is
        // pointer-events:none and has nothing to submit.
        holder.innerHTML = `<iframe src="${esc(src)}" sandbox="allow-scripts allow-same-origin" tabindex="-1" aria-hidden="true" scrolling="no" loading="lazy"
          style="position:absolute;top:0;left:0;width:${logicalW}px;height:${logicalH}px;border:0;transform:scale(${scale.toFixed(4)});transform-origin:top left;pointer-events:none;"></iframe>`;
        holder.dataset.libMountedFrame = '1';
        _libraryMounted.push(holder);
      };
      // Mount the first screenful immediately rather than waiting to be told
      // they are visible: they demonstrably are, an observer that never fires
      // leaves a wall of blank tiles, and previews arriving one beat late reads
      // as the panel being broken.
      holders.slice(0, LIBRARY_PREVIEW_BUDGET).forEach(mount);
      if (typeof IntersectionObserver !== 'function' || holders.length <= LIBRARY_PREVIEW_BUDGET) return;
      _libraryObserver = new IntersectionObserver((entries) => {
        entries.filter(e => e.isIntersecting).forEach(e => mount(e.target));
      }, { root: document.getElementById('tc-library-body'), rootMargin: '160px' });
      holders.slice(LIBRARY_PREVIEW_BUDGET).forEach(h => _libraryObserver.observe(h));
    }

    async function chooseLibraryProject(root, label) {
      if (!root) return;
      closeLibraryMenu();
      if (!window.ThomasUnifiedModes) return;
      try { await window.ThomasUnifiedModes.newConversation(root, label); }
      catch (e) { /* the mode surface reports its own failures */ }
    }

    function readFile(file) {
      return new Promise(res => {
        const r = new FileReader();
        if (/^image\//.test(file.type)) { r.onload = () => res({ kind: 'image', data_url: r.result, name: file.name }); r.onerror = () => res(null); r.readAsDataURL(file); }
        else { r.onload = () => res({ kind: 'doc', name: file.name, text: String(r.result || '') }); r.onerror = () => res(null); r.readAsText(file); }
      });
    }
    async function onFiles(fileList) {
      const files = Array.from(fileList || []);
      for (const f of files) { const a = await readFile(f); if (!a) continue; if (a.kind === 'image') state.images.push({ data_url: a.data_url, name: a.name }); else state.docs.push({ name: a.name, text: a.text }); }
      renderAttachments();
    }
    function renderAttachments() {
      const row = document.getElementById('tc-attach-row'); if (!row) return;
      const items = state.docs.map((d, i) => ({ type: 'doc', i, name: d.name })).concat(state.images.map((im, i) => ({ type: 'img', i, name: im.name })));
      if (!items.length) { row.style.display = 'none'; row.innerHTML = ''; return; }
      row.style.display = 'flex'; row.innerHTML = '';
      items.forEach(it => {
        const chip = document.createElement('span');
        chip.style.cssText = 'display:inline-flex;align-items:center;gap:6px;padding:5px 9px;border-radius:8px;background:var(--c-surface-2);border:1px solid var(--c-border);font-size:12px;color:var(--c-text);max-width:200px;';
        chip.innerHTML = '<i class="ph ' + (it.type === 'img' ? 'ph-image' : 'ph-file-text') + '" style="font-size:13px;color:var(--c-accent);"></i><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(it.name) + '</span>';
        const x = document.createElement('button'); x.innerHTML = '<i class="ph ph-x" style="font-size:12px;"></i>'; x.style.cssText = 'border:0;background:transparent;color:var(--c-muted);cursor:pointer;padding:0;display:flex;';
        x.addEventListener('click', () => { if (it.type === 'doc') state.docs.splice(it.i, 1); else state.images.splice(it.i, 1); renderAttachments(); });
        chip.appendChild(x); row.appendChild(chip);
      });
    }

    let recognition = null;
    function setupMic() {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      const btn = document.getElementById('tc-mic-btn'); if (!btn) return;
      if (!SR) { btn.title = 'Voice input not supported in this browser'; btn.style.opacity = '0.45'; return; }
      // Continuous listening: stays on through pauses, stops only after ~5s of
      // silence (or a manual click). No auto cut-off mid-sentence.
      recognition = new SR(); recognition.continuous = true; recognition.interimResults = true; recognition.lang = 'en-US';
      const SILENCE_MS = 5000;
      let base = '', finalChunk = '', silenceTimer = null, stopRequested = false;
      function micOn() { btn.style.color = 'var(--c-accent-ink)'; btn.style.background = 'var(--c-accent)'; btn.title = 'Listening… (stops after a pause)'; }
      function micOff() { btn.style.color = 'var(--c-dim)'; btn.style.background = 'transparent'; btn.title = 'Voice input'; }
      function resetSilence() { if (silenceTimer) clearTimeout(silenceTimer); silenceTimer = setTimeout(() => { stopRequested = true; try { recognition.stop(); } catch (e) {} }, SILENCE_MS); }
      recognition.onresult = (e) => {
        let interim = '';
        for (let i = e.resultIndex; i < e.results.length; i++) { const r = e.results[i]; if (r.isFinal) finalChunk += r[0].transcript; else interim += r[0].transcript; }
        const combined = ((base ? base + ' ' : '') + finalChunk + interim).replace(/\s+/g, ' ').replace(/^\s+/, '');
        state.input = combined; inputEl.value = combined; autosize(); syncDynamic();
        resetSilence();
      };
      recognition.onerror = () => { /* keep listening; onend handles restart */ };
      recognition.onend = () => {
        if (state.listening && !stopRequested) { try { recognition.start(); return; } catch (e) {} }
        state.listening = false; if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; } micOff();
      };
      btn.addEventListener('click', () => {
        if (state.listening) { stopRequested = true; try { recognition.stop(); } catch (e) {} return; }
        base = state.input.trim(); finalChunk = ''; stopRequested = false; state.listening = true; micOn();
        try { recognition.start(); resetSilence(); } catch (e) { state.listening = false; micOff(); }
      });
    }

    return {
      toggleToolsMenu, closeToolsMenu, renderToolsMenu,
      toggleLibraryMenu, closeLibraryMenu, positionLibraryMenu, renderLibraryMenu,
      libraryVisibleProjects, libraryCardHTML, mountLibraryPreviews,
      teardownLibraryPreviews, loadLibraryProjects, chooseLibraryProject,
      relativeWhen, readFile, onFiles, renderAttachments, setupMic,
    };
  }

  window.ThomasChatComposerPanels = { create: create };
})();
