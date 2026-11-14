/* The panels the composer bar opens: the AI-settings sheet behind "Tools",
   the Thomas Library project picker, the attachment chips and voice input.

   Lifted out of chat.html's single inline <script> when that page passed the
   3000-line ceiling in tests/test_architecture.py::test_frontend_file_sizes
   (3310 -> 2975 lines). The bodies below are exactly what the page ran. The
   only change is that the closure values they used to read directly now
   arrive as arguments, and the page destructures the same names back out, so
   every call site in chat.html is untouched.

   DIAL_FIELDS and saveDials stay in the page on purpose: a UX guard
   (tests/test_web_evolve_chat_ux.py) pins the effort vocabulary to chat.html itself, and setProfile still calls saveDials. */
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

    // Which executor Code will actually use for the model currently picked. The
    // predicate is deliberately the same one unified_code_lifecycle.js applies when
    // it builds the request -- two spellings of one rule is how they drift apart.
    function codeRunsClaudeCli() {
      if (state.surfaceMode !== 'code') return false;
      const picked = String(state.modelId || '');
      // An empty modelId is "we lost the client's model state", NOT "a non-GPT
      // model was chosen". unified_code_lifecycle.js already draws that line —
      // `model: modelId ? (...) : undefined` sends no model at all and lets the
      // server resolve the configured default. This predicate did not, so a
      // dropped modelId made the sheet announce the Claude executor under a chip
      // reading GPT-5.6 Sol, whose id (gpt-5.6-sol) routes to ChatGPT. The two
      // spellings of one rule had drifted in exactly the way the comment above
      // warns about; say nothing when we do not know what was picked.
      if (!picked) return false;
      return !picked.startsWith('gpt-');
    }

    // Build has two engines: ChatGPT for GPT models, the Claude CLI for Claude
    // models. Mirrors forge_code_settings.from_payload, which is the authority
    // and now REFUSES what it cannot run instead of substituting — so drift here
    // costs a clear refusal naming the model, never a silent swap. Lives in this
    // module rather than chat.html, which is at its frontend size ceiling.
    function buildCanRunModel(p, m) {
      const id = String((m && m.id) || '').toLowerCase().replace(/^claude:/, '');
      const provider = String((p && p.provider) || '').toLowerCase();
      const profileName = String((p && p.name) || '').toLowerCase();
      if (id.startsWith('gpt-') || provider === 'openai_codex') return true;
      if (profileName.startsWith('codex') || profileName.startsWith('chatgpt')) return true;
      return /^(claude\b|claude-|sonnet|opus|haiku)/.test(id);
    }

    function hiddenForBuildNote(count) {
      return count + (count === 1 ? ' model is' : ' models are')
        + ' hidden here: Build runs GPT models through your ChatGPT account and Claude models'
        + ' through the Claude CLI. They are still available in Chat.';
    }

    function dialUnsupportedNote(key) {
      if (key !== 'effort' || !codeRunsClaudeCli()) return '';
      // Say the cause, not just the consequence.
      //
      // This used to read "this model runs on the Claude executor, which has no
      // reasoning-effort control" -- true, and useless. It explained why one
      // dial was inert while stepping over the thing worth knowing: Build has
      // exactly two engines (ChatGPT for gpt-* ids, the Claude CLI for
      // everything else), so a non-gpt pick is rewritten to claude:sonnet
      // before dispatch. The model named in the picker is not the model that
      // writes the code. Reasoning effort being ignored is a symptom of that.
      return 'Not applied in Code: Build runs this on Claude Sonnet. Thomas Code has two engines — ChatGPT for '
        + 'GPT models and the Claude CLI for everything else — so the model above is '
        + 'substituted here, and reasoning effort does not apply.';
    }

    // Options can be limited to certain surfaces (see DIAL_FIELDS). An option the
    // current surface does not offer must never be silently dropped while it is
    // the stored value -- that would show a control whose displayed selection is
    // not the one being sent.
    function optionsFor(f) {
      return f.opts.filter(o => {
        const meta = o[3] || {};
        if (!meta.modes) return true;
        if (String(state.dials[f.key]) === String(o[0])) return true;
        return meta.modes.indexOf(String(state.surfaceMode || 'chat')) !== -1;
      });
    }

    // Levels retired from the picker still exist in localStorage and in the
    // engine. 'read_only' and 'full' were removed from this sheet -- the first
    // because Autonomy already owns "do nothing without me", the second because
    // it meant every drive on the machine while sitting under a label ('Full')
    // one word away from 'Full PC'. Map each to the nearest surviving level
    // rather than leaving a select whose value it cannot display.
    const RETIRED_DIAL_VALUES = { fileAccess: { read_only: 'workspace', full: 'pc' } };
    function migrateRetiredDials() {
      let changed = false;
      Object.keys(RETIRED_DIAL_VALUES).forEach(key => {
        const replacement = RETIRED_DIAL_VALUES[key][String(state.dials[key])];
        if (replacement) { state.dials[key] = replacement; changed = true; }
      });
      if (state.dials.tokenEconomy !== undefined) { delete state.dials.tokenEconomy; changed = true; }
      if (changed) saveDials();
    }

    // Raising a limit asks at the operating system -- Windows Hello or your
    // password -- not in this page. This used to be window.confirm(), an OK box
    // anything driving the browser can click, and the server took whatever level
    // a request carried. Now the server is the lock (thomas/server/dial_elevation):
    // a level it has not seen approved runs one step lower whatever this menu
    // says. The prompt is only how you give the approval. Lowering never asks:
    // a smaller blast radius needs no defending, and a prompt on the safe
    // direction teaches people to click through prompts.
    const SERVER_DIAL = { autonomy: 'autonomy', fileAccess: 'file_access', guardrails: 'guardrails' };
    const ELEVATION_REFUSED = {
      declined_recently: 'You said no a moment ago. Try again in a few seconds.',
      prompt_open: 'A password prompt is already open. Answer that one first.',
    };

    async function requestElevation(fieldKey, value) {
      let answer = null;
      try {
        const res = await fetch('/api/security/elevate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dial: SERVER_DIAL[fieldKey], value: value }),
        });
        answer = await res.json();
      } catch (_) {
        answer = { approved: false, reason: 'unreachable' };
      }
      // Anything but an explicit approval is a no.
      return answer && typeof answer === 'object' ? answer : ({ approved: false });
    }

    // A saved raised level outlives the approval behind it: approvals are kept
    // in the server's memory, so a restart forgets them while this browser still
    // remembers "Autopilot". Ask the server what it will honour and show that.
    async function reconcileElevatedDials() {
      const pairs = [];
      DIAL_FIELDS.forEach(f => {
        if (!SERVER_DIAL[f.key]) return;
        const picked = f.opts.filter(o => String(o[0]) === String(state.dials[f.key]))[0];
        if (picked && picked[3] && picked[3].elevates) {
          pairs.push(SERVER_DIAL[f.key] + '=' + encodeURIComponent(String(state.dials[f.key])));
        }
      });
      if (!pairs.length) return;
      let honoured;
      try {
        const res = await fetch('/api/security/elevation?' + pairs.join('&'));
        honoured = ((await res.json()) || {}).honoured || {};
      } catch (_) { return; }
      let changed = false;
      DIAL_FIELDS.forEach(f => {
        const server = honoured[SERVER_DIAL[f.key]];
        if (server === undefined || String(server) === String(state.dials[f.key])) return;
        state.dials[f.key] = f.num ? parseInt(server, 10) : String(server);
        changed = true;
      });
      if (!changed) return;
      saveDials();
      renderToolsMenu();
      if (typeof syncDynamic === 'function') syncDynamic();
    }
    reconcileElevatedDials().catch(() => {});

    // A setting Thomas asked for on a card and you approved (ask_user_panel.js
    // applies it and announces it here, where the live dials are kept).
    if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
      window.addEventListener('thomas:dial-set', (event) => {
        const detail = (event && event.detail) || {};
        if (!detail.key || !(detail.key in state.dials)) return;
        state.dials[detail.key] = detail.value;
        saveDials();
        renderToolsMenu();
        if (typeof syncDynamic === 'function') syncDynamic();
      });
    }

    function renderToolsMenu() {
      const wrap = document.getElementById('tc-tools-menu'); if (!wrap) return;
      migrateRetiredDials();
      // Looks are classes (chat_shell.css .tc-tools-*) so Build can restyle them.
      wrap.innerHTML = '<div class="tc-tools-heading">AI settings</div>';
      DIAL_FIELDS.forEach(f => {
        const row = document.createElement('label'); row.className = 'tc-tools-field';
        const span = document.createElement('span'); span.textContent = f.label;
        const sel = document.createElement('select');
        const shown = optionsFor(f);
        shown.forEach(o => { const el = document.createElement('option'); el.value = String(o[0]); el.textContent = o[1]; if (String(o[0]) === String(state.dials[f.key])) el.selected = true; sel.appendChild(el); });
        row.appendChild(span); row.appendChild(sel); wrap.appendChild(row);

        // The description of whatever is selected, always on screen. The label
        // alone could not carry the difference between "your home folder" and
        // "every drive", and that difference is the whole point of the control.
        const desc = document.createElement('div');
        desc.className = 'tc-dial-desc';
        const describe = () => {
          const current = f.opts.filter(o => String(o[0]) === String(state.dials[f.key]))[0];
          desc.textContent = current ? String(current[2] || '') : '';
        };
        describe();

        sel.addEventListener('change', async () => {
          const picked = f.opts.filter(o => String(o[0]) === String(sel.value))[0];
          const meta = (picked && picked[3]) || {};
          const previous = state.dials[f.key];
          if (meta.elevates && String(sel.value) !== String(previous)) {
            sel.disabled = true;
            desc.textContent = 'Waiting for your approval at the password prompt…';
            const answer = await requestElevation(f.key, sel.value);
            sel.disabled = false;
            if (!answer.approved) {
              sel.value = String(previous);
              describe();
              desc.textContent = ELEVATION_REFUSED[answer.reason]
                || (answer.reason === 'unreachable'
                  ? 'Thomas could not reach the password prompt, so nothing changed.'
                  : 'Not approved, so nothing changed.');
              return;
            }
          }
          state.dials[f.key] = f.num ? parseInt(sel.value, 10) : sel.value;
          saveDials();
          describe();
        });
        wrap.appendChild(desc);
        // Say it BEFORE the run, not after.
        //
        // Code has exactly two executors: anything whose id does not start with
        // `gpt-` is dispatched to the Claude CLI (unified_code_lifecycle.js sends
        // `claude:sonnet`), and that executor exposes no reasoning-effort control.
        // Both facts were already known and already reported -- but only in the
        // capability report, AFTER the run, as "substituted" and "unsupported".
        // Until then this sheet showed a live six-position dial and the model you
        // picked, so the only place the truth appeared was the post-mortem.
        const noteFor = dialUnsupportedNote(f.key);
        if (noteFor) {
          const hint = document.createElement('div');
          hint.className = 'tc-dial-note';
          hint.textContent = noteFor;
          wrap.appendChild(hint);
        }
      });
      const memRow = document.createElement('label'); memRow.className = 'tc-tools-field tc-tools-memory';
      const memSpan = document.createElement('span'); memSpan.textContent = 'Memory';
      const memChk = document.createElement('input'); memChk.type = 'checkbox'; memChk.checked = !!state.dials.memory;
      memChk.addEventListener('change', () => { state.dials.memory = memChk.checked; saveDials(); });
      memRow.appendChild(memSpan); memRow.appendChild(memChk); wrap.appendChild(memRow);
    }
    // aria-expanded: the open state for assistive tech and for the stylesheet.
    function showToolsMenu(open) {
      state.toolsMenuOpen = open;
      const m = document.getElementById('tc-tools-menu'); if (m) m.style.display = open ? 'block' : 'none';
      const btn = document.getElementById('tc-tools-btn'); if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    function toggleToolsMenu() {
      showToolsMenu(!state.toolsMenuOpen);
      if (state.toolsMenuOpen) renderToolsMenu();
    }
    function closeToolsMenu() { showToolsMenu(false); }

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
    state.libraryNewProject = null;
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

    // You reported this chooser opening "off to the right rather than centered". It is
    // `position:absolute; left:0` inside #tc-code-project-wrap, the THIRD control in the
    // composer's button row (after "+" and "Tools"), so `left:0` was the folder button's
    // left edge, ~140px into the composer card, while the panel is up to 760px wide: sized
    // to the reading column but started a third of the way across it. Resizing made it
    // worse: across the viewer in Build's viewer layout, off the screen at phone widths.
    //
    // Markup cannot fix that: the offset needed is the distance from the trigger to the
    // column centre, and neither is known until layout, so measure both. #tc-composer-rail
    // IS the reading column (.tc-rail in chat_shell.css); the composer card fills it, so
    // their centres agree. Width is capped by the rail, the 760px design width and the
    // viewport; the left edge is then clamped so a phone-width screen keeps a 16px margin.
    const LIBRARY_MENU_MAX_WIDTH = 760;
    const LIBRARY_MENU_EDGE_MARGIN = 16;
    function positionLibraryMenu() {
      const m = document.getElementById('tc-code-library-menu');
      const wrap = document.getElementById('tc-code-project-wrap');
      const rail = document.getElementById('tc-composer-rail');
      if (!m || !wrap || !rail) return;
      const margin = LIBRARY_MENU_EDGE_MARGIN;
      const railBox = rail.getBoundingClientRect();
      // A rail with no box is Build's surface mid-swap, not a column to centre
      // on -- and the observer below fires on the way to a real width as well
      // as at it. Writing that zero through would collapse an open chooser to
      // nothing until the next notification, which reads as the panel closing
      // itself. Keep the last good geometry until there is a column to measure.
      if (railBox.width <= 0) return;
      const wrapLeft = wrap.getBoundingClientRect().left;
      const viewport = window.innerWidth;
      const width = Math.max(0, Math.min(LIBRARY_MENU_MAX_WIDTH, railBox.width, viewport - 2 * margin));
      // chat_shell.css already makes every box border-box, so this changes
      // nothing today. It is pinned because the arithmetic below treats the
      // written width as the VISIBLE width, and the panel has a 1px border:
      // under content-box the same number would render 2px wider and half a
      // border off centre, which is a strange thing to leave resting on a
      // global reset in another file.
      m.style.boxSizing = 'border-box';
      // Rewritten on every call, never accumulated, so the narrow-screen width
      // does not survive into a later wide layout.
      m.style.width = `${width}px`;
      const left = Math.max(margin, Math.min(
        railBox.left + (railBox.width - width) / 2,
        viewport - margin - width,
      ));
      // `left` is viewport-relative; the panel's containing block is the wrap.
      m.style.left = `${left - wrapLeft}px`;
    }
    window.addEventListener('resize', () => { if (state.libraryMenuOpen) positionLibraryMenu(); });
    // Build's activity drawer and viewer resize the rail WITHOUT a viewport
    // resize -- unified_code_mode.css drives both off [data-code-side] on the
    // shell. An open chooser has to follow the column it is centred on, so
    // watch the rail itself rather than the window. Clicking the sidebar
    // toggle is not a case to handle here: chat_shell_bindings.js closes this
    // panel on any click outside [data-code-library-wrap].
    const libraryRail = document.getElementById('tc-composer-rail');
    if (libraryRail && typeof ResizeObserver === 'function') {
      new ResizeObserver(() => { if (state.libraryMenuOpen) positionLibraryMenu(); }).observe(libraryRail);
    }

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
        if (data.refreshing && state.libraryMenuOpen) {
          setTimeout(() => { if (state.libraryMenuOpen) loadLibraryProjects(); }, 800);
        }
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
      if (state.libraryNewProject) { renderLibraryProjectForm(m); return; }
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
      const selfEditButton = document.createElement('button');
      selfEditButton.type = 'button';
      selfEditButton.dataset.libAction = 'self-edit';
      selfEditButton.textContent = 'Improve Thomas';
      selfEditButton.style.cssText = 'margin:10px 14px;padding:9px;border:1px solid var(--c-border);border-radius:8px;background:var(--c-surface);color:var(--c-text);cursor:pointer';
      m.prepend(selfEditButton);
      mountLibraryPreviews();
    }

    function renderLibraryProjectForm(menu) {
      teardownLibraryPreviews();
      const draft = state.libraryNewProject;
      const focused = document.activeElement && document.activeElement.id === 'tc-library-project-name';
      menu.innerHTML = `<form id="tc-library-new-project" style="padding:18px;display:grid;gap:12px;">
        <label for="tc-library-project-name" style="font-weight:700;color:var(--c-text);">Name your new project</label>
        <input id="tc-library-project-name" name="projectName" required maxlength="64" autocomplete="off" placeholder="My new project" value="${esc(draft.name)}" ${draft.busy ? 'disabled' : ''}
          style="width:100%;padding:10px;border:1px solid var(--c-border);border-radius:9px;background:var(--c-surface);color:var(--c-text);font:inherit;">
        <p role="status" style="margin:0;color:var(--c-muted);font-size:13px;">${esc(draft.error || 'Thomas will create a separate folder for this project.')}</p>
        <div style="display:flex;justify-content:flex-end;gap:8px;">
          <button type="button" data-lib-action="cancel-new" ${draft.busy ? 'disabled' : ''}>Cancel</button>
          <button type="submit" ${draft.busy ? 'disabled' : ''}>${draft.busy ? 'Creating…' : 'Create project'}</button>
        </div>
      </form>`;
      if (focused && !draft.busy) document.getElementById('tc-library-project-name')?.focus();
    }

    async function submitLibraryProject() {
      const draft = state.libraryNewProject;
      if (!draft || draft.busy) return;
      const name = draft.name.trim();
      if (!name) {
        draft.error = 'Enter a project name.';
        renderLibraryMenu();
        document.getElementById('tc-library-project-name')?.focus();
        return;
      }
      draft.busy = true;
      draft.error = '';
      renderLibraryMenu();
      try {
        const created = await window.ThomasUnifiedModes?.newConversation('', name, { newProjectName: name });
        if (created !== true) throw new Error('Could not create this project. Try again when Thomas is ready.');
        if (state.libraryNewProject === draft) {
          state.libraryNewProject = null;
          state.libraryProjects = null;
          closeLibraryMenu();
          inputEl.focus();
        }
      } catch (error) {
        if (state.libraryNewProject === draft) draft.error = error.message || 'Could not create this project.';
      } finally {
        draft.busy = false;
        renderLibraryMenu();
      }
    }

    function bindLibraryActions() {
      const menu = document.getElementById('tc-code-library-menu');
      if (!menu) return;
      menu.addEventListener('click', event => {
        const action = event.target.closest('[data-lib-action]');
        if (action) {
          const kind = action.getAttribute('data-lib-action');
          if (kind === 'self-edit') {
            closeLibraryMenu();
            void window.ThomasSelfEdit?.selectThomas(chooseLibraryProject).catch(error => window.alert(error.message));
          } else if (kind === 'new') {
            state.libraryNewProject = { name: '', error: '', busy: false };
            renderLibraryMenu();
            document.getElementById('tc-library-project-name')?.focus();
          } else if (kind === 'cancel-new' && !state.libraryNewProject?.busy) {
            state.libraryNewProject = null;
            renderLibraryMenu();
            menu.querySelector('[data-lib-action="new"]')?.focus();
          } else if (kind === 'browse') {
            closeLibraryMenu();
            window.ThomasUnifiedModes?.pickProject();
          }
          return;
        }
        const card = event.target.closest('[data-lib-card]');
        if (card) void chooseLibraryProject(card.getAttribute('data-lib-card'), card.getAttribute('data-lib-label'));
      });
      menu.addEventListener('input', event => {
        if (event.target.id === 'tc-library-project-name' && state.libraryNewProject) state.libraryNewProject.name = event.target.value;
      });
      menu.addEventListener('submit', event => {
        if (event.target.id !== 'tc-library-new-project') return;
        event.preventDefault();
        void submitLibraryProject();
      });
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

    async function readFile(file) {
      if (file.size > 5000000) return ({ kind: 'doc', name: file.name, error: 'Choose a file no larger than 5 MB.' });
      if (/^image\//.test(file.type)) {
        return new Promise(res => {
          const r = new FileReader();
          r.onload = () => res({ kind: 'image', data_url: r.result, name: file.name });
          r.onerror = () => res({ kind: 'doc', name: file.name, error: 'This image could not be read.' });
          r.readAsDataURL(file);
        });
      }
      // Binary documents must be decoded before the composer promises they can
      // be read. The server owns format detection, size limits and PDF parsing.
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 15000);
      try {
        const body = new FormData();
        body.append('document', file, file.name);
        const response = await fetch('/api/v2/chat/documents/extract', { method: 'POST', body, signal: controller.signal });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'This document could not be read.');
        return ({ ...result.document, kind: 'doc', name: file.name });
      } catch (error) {
        return ({ kind: 'doc', name: file.name, error: error.name === 'AbortError'
          ? 'Document reading timed out. Try a smaller file.' : (error.message || 'This document could not be read.') });
      } finally { clearTimeout(timer); }
    }
    async function onFiles(fileList) {
      const files = Array.from(fileList || []);
      // Bind uploads to the draft that selected them, even if conversation or
      // draft state is replaced while extraction is running.
      const docs = state.docs;
      const images = state.images;
      const entries = files.map(file => ({ file, pending: { name: file.name, text: '', pending: true } }));
      entries.forEach(entry => docs.push(entry.pending)); renderAttachments();
      for (const { file: f, pending } of entries) {
        if (!docs.includes(pending)) continue;
        const a = await readFile(f);
        const pendingIndex = docs.indexOf(pending);
        if (pendingIndex < 0) continue; // Removed while reading; do not reattach it.
        if (a.kind === 'image') {
          docs.splice(pendingIndex, 1);
          images.push({ data_url: a.data_url, name: a.name });
        } else {
          Object.assign(pending, a, { text: a.text || '', pending: false, ...(a.error ? { error: a.error } : {}) });
        }
      }
      renderAttachments();
    }
    function renderAttachments() {
      syncDynamic();
      const row = document.getElementById('tc-attach-row'); if (!row) return;
      const items = state.docs.map((d, i) => ({ type: 'doc', i, name: d.name, error: d.error, pending: d.pending })).concat(state.images.map((im, i) => ({ type: 'img', i, name: im.name })));
      if (!items.length) { row.style.display = 'none'; row.innerHTML = ''; return; }
      row.style.display = 'flex'; row.innerHTML = '';
      items.forEach(it => {
        const chip = document.createElement('span');
        chip.style.cssText = 'display:inline-flex;align-items:center;gap:6px;padding:5px 9px;border-radius:8px;background:var(--c-surface-2);border:1px solid var(--c-border);font-size:12px;color:var(--c-text);max-width:200px;';
        chip.innerHTML = '<i class="ph ' + (it.type === 'img' ? 'ph-image' : 'ph-file-text') + '" style="font-size:13px;color:var(--c-accent);"></i><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(it.name) + '</span>';
        if (it.pending) {
          chip.setAttribute('role', 'status');
          chip.innerHTML = '<span>' + esc(it.name + ' — Reading… Wait to send.') + '</span>';
        }
        if (it.error) {
          chip.setAttribute('role', 'alert');
          chip.style.maxWidth = '100%';
          chip.innerHTML = '<span>' + esc(it.name + ' — Not attached: ' + it.error) + '</span>';
        }
        const x = document.createElement('button'); x.innerHTML = '<i class="ph ph-x" style="font-size:12px;"></i>'; x.style.cssText = 'border:0;background:transparent;color:var(--c-muted);cursor:pointer;padding:0;display:flex;';
        x.setAttribute('aria-label', 'Remove ' + it.name);
        x.addEventListener('click', () => { if (it.type === 'doc') state.docs.splice(it.i, 1); else state.images.splice(it.i, 1); renderAttachments(); });
        chip.appendChild(x); row.appendChild(chip);
      });
    }

    function attachmentsReady() {
      if (!state.docs.some(doc => doc.pending)) return true;
      inputEl.setCustomValidity('Wait for file extraction to finish before sending.');
      inputEl.reportValidity();
      return false;
    }

    function syncAttachmentState(modeBusy) {
      const pending = state.docs.some(doc => doc.pending);
      const button = document.getElementById('tc-send');
      if (button) {
        button.disabled = pending && !(modeBusy && !state.input.trim());
        // Build names its own button (Pause, Resume, Stop) and marks it; "Send" here used to overwrite that tooltip on every sync.
        if (pending) button.title = 'Wait for file extraction before sending';
        else if (!button.getAttribute('data-primary')) button.title = 'Send';
      }
      if (!pending && inputEl.setCustomValidity) inputEl.setCustomValidity('');
    }

    // The mic lives in js/chat_mic.js; it reads the same state and composer hooks.
    function setupMic() {
      if (window.ThomasChatMic) window.ThomasChatMic.create({ state, inputEl, autosize, syncDynamic }).setupMic();
    }

    return {
      toggleToolsMenu, closeToolsMenu, renderToolsMenu, buildCanRunModel, hiddenForBuildNote,
      toggleLibraryMenu, closeLibraryMenu, positionLibraryMenu, renderLibraryMenu,
      libraryVisibleProjects, libraryCardHTML, mountLibraryPreviews,
      teardownLibraryPreviews, loadLibraryProjects, chooseLibraryProject, bindLibraryActions,
      relativeWhen, readFile, onFiles, renderAttachments, setupMic, attachmentsReady, syncAttachmentState,
    };
  }
  window.ThomasChatComposerPanels = { create: create };
})();
