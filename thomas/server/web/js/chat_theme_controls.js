/* Chat theme controls. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {
    function botHTML(p) {
      return window.ThomasBot ? window.ThomasBot.markup(p) : '';
    }

    function hydrateBots() {
      document.querySelectorAll('[data-bot]').forEach(el => {
        el.innerHTML = botHTML({ primary: el.dataset.primary, secondary: el.dataset.secondary, trim: el.dataset.trim, glow: el.dataset.glow, scale: el.dataset.scale, flame: el.dataset.flame });
      });
    }

    function avatar(size, radius, dotW, dotH) {
      return `<span style="width: ${size}px; height: ${size}px; border-radius: ${radius}px; background: var(--c-accent); display: grid; place-items: center; flex: 0 0 auto;">
        <span style="display: flex; gap: 3px;"><span style="width: ${dotW}px; height: ${dotH}px; border-radius: 1px; background: var(--c-accent-ink);"></span><span style="width: ${dotW}px; height: ${dotH}px; border-radius: 1px; background: var(--c-accent-ink);"></span></span>
      </span>`;
    }

    function applyTheme(name) {
      const t = deps.THEMES[name]; if (!t) return;
      Object.entries(t.vars).forEach(([k, v]) => deps.shell.style.setProperty(k, v));
      if (window.ThomasWorkspaceShell) window.ThomasWorkspaceShell.applyTheme(name, { vars: t.vars, persist: false });
      deps.shell.style.setProperty('--sw-1', t.sw[0]); deps.shell.style.setProperty('--sw-2', t.sw[1]); deps.shell.style.setProperty('--sw-3', t.sw[2]);
      const m = deps.THEME_META[name];
      if (m) {
        deps.shell.style.setProperty('--bot-primary', m.bot[0]); deps.shell.style.setProperty('--bot-secondary', m.bot[1]); deps.shell.style.setProperty('--bot-glow', m.bot[2]); deps.shell.style.setProperty('--bot-trim', m.trim);
        deps.shell.style.setProperty('--font-head', m.fontHead); deps.shell.style.setProperty('--font-label', m.fontLabel);
        deps.shell.style.setProperty('--r-card', m.rCard); deps.shell.style.setProperty('--r-composer', m.rComposer);
        deps.shell.style.setProperty('--c-menu-bg', m.menuBg); deps.shell.style.setProperty('--composer-accent', m.composerAccent); deps.shell.style.setProperty('--msg-rule-on', m.msgRule);
      }
      deps.shell.dataset.theme = name;
      document.getElementById('tc-theme-name').textContent = t.name;
      if (m) { document.getElementById('tc-welcome-title').textContent = m.welcome[0]; document.getElementById('tc-welcome-sub').textContent = m.welcome[1]; }
      const heroBot = deps.welcomeEl.querySelector('[data-bot]');
      if (heroBot) heroBot.innerHTML = botHTML({ primary: 'var(--bot-primary)', secondary: 'var(--bot-secondary)', trim: 'var(--bot-trim)', glow: 'var(--bot-glow)', scale: heroBot.dataset.scale, flame: heroBot.dataset.flame });
      document.querySelectorAll('.tc-workspace-frame').forEach((frame) => {
        if (frame.contentWindow && window.ThomasWorkspaceShell) window.ThomasWorkspaceShell.sendTheme(frame, name, t.vars);
      });
      if (window.ThomasOverlay && window.ThomasOverlay.pinTokens) window.ThomasOverlay.pinTokens();
    }

    function selectTheme(name) {
      deps.state.theme = name; deps.state.themeMenuOpen = false; applyTheme(name);
      try { localStorage.setItem('thomas_chat_theme', name); } catch (e) {}
      renderThemeMenu(); document.getElementById('tc-theme-menu').style.display = 'none';
    }

    function toggleThemeMenu() {
      deps.state.themeMenuOpen = !deps.state.themeMenuOpen;
      document.getElementById('tc-theme-menu').style.display = deps.state.themeMenuOpen ? 'block' : 'none';
      if (deps.state.themeMenuOpen) renderThemeMenu();
    }

    function renderThemeMenu() {
      const wrap = document.getElementById('tc-theme-options');
      wrap.innerHTML = '';
      ['nebula', 'light'].filter(key => deps.THEMES[key]).forEach(key => {  // Dark (stored as nebula) and Light
        const t = deps.THEMES[key], sel = key === deps.state.theme;
        const b = document.createElement('button');
        b.className = 'hv-soft';
        b.style.cssText = `width: 100%; display: flex; align-items: center; gap: 11px; padding: 9px 9px; border-radius: 10px; border: 1px solid ${sel ? 'var(--c-accent-line)' : 'transparent'}; background: ${sel ? 'var(--c-accent-soft)' : 'transparent'}; color: var(--c-text); font-family: inherit; cursor: pointer; text-align: left; transition: all .14s; margin-bottom: 2px;`;
        b.innerHTML = `<span style="display: inline-flex; border-radius: 7px; overflow: hidden; border: 1px solid var(--c-border-2); flex: 0 0 auto; box-shadow: 0 2px 8px rgba(0,0,0,0.25);">
            <span style="width: 14px; height: 30px; background: ${t.sw[0]};"></span>
            <span style="width: 14px; height: 30px; background: ${t.sw[1]};"></span>
            <span style="width: 14px; height: 30px; background: ${t.sw[2]};"></span>
          </span>
          <span style="flex: 1; min-width: 0;">
            <span style="display: block; font-size: 13.5px; font-weight: 700;">${deps.esc(t.name)}</span>
            <span style="display: block; font-size: 11.5px; color: var(--c-muted);">${deps.esc(t.tagline)}</span>
          </span>
          <i class="ph ph-check" style="font-size: 15px; color: var(--c-accent); opacity: ${sel ? '1' : '0'};"></i>`;
        b.addEventListener('click', () => selectTheme(key));
        wrap.appendChild(b);
      });
    }

    let mounted = false;
    async function mountBuildBadge() {
      if (mounted) return;
      mounted = true;
      const badge = document.getElementById('tc-build-badge');
      const label = document.getElementById('tc-build-text');
      const port = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
      let buildLine = ':' + port;
      let generation = null;
      let previousGeneration = null;
      let restarting = false;
      let pending = false;
      let cancelling = false;
      let polling = false;
      let lastStatus = null;

      let embedded = false;
      try { embedded = new URLSearchParams(window.location.search).get('embed') === '1'; } catch (e) { /* A plain window is not embedded. */ }
      const banner = document.createElement('div');
      banner.id = 'tc-restart-notice';
      banner.hidden = true;
      banner.style.cssText = 'display:none; align-items:center; gap:10px; padding:5px 14px; font-size:12px; line-height:1.3; background:var(--c-menu-bg, #282828); color:var(--c-muted, #aaa); border-bottom:1px solid var(--c-border-2, #777);';
      const noticeText = document.createElement('span');
      noticeText.style.cssText = 'flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;';
      const buttonStyle = 'padding:2px 10px; font-size:12px; border-radius:6px; border:1px solid var(--c-border-2, #777); background:transparent; color:var(--c-text, white); cursor:pointer;';
      const restartButton = document.createElement('button');
      restartButton.type = 'button';
      restartButton.textContent = 'Restart now';
      restartButton.style.cssText = buttonStyle;
      const cancelButton = document.createElement('button');
      cancelButton.type = 'button';
      cancelButton.textContent = 'Cancel restart';
      cancelButton.style.cssText = buttonStyle;
      cancelButton.hidden = true;
      banner.appendChild(noticeText);
      banner.appendChild(restartButton);
      banner.appendChild(cancelButton);
      const top = deps.shell || document.body;
      top.insertBefore(banner, top.firstChild);

      const quiet = document.createElement('div');
      quiet.id = 'tc-swap-status';
      quiet.hidden = true;
      quiet.style.cssText = 'padding:2px 16px; color:var(--c-muted, #888); font-size:12px;';
      top.insertBefore(quiet, banner.nextSibling);

      function progress(status) {
        const checks = status && status.checks_running != null ? Math.max(0, Number(status.checks_running) || 0) : 'unknown';
        const seconds = Math.floor(Math.max(0, Number(status && status.elapsed_s) || 0));
        const elapsed = seconds >= 60 ? Math.floor(seconds / 60) + ' min' : seconds + 's';
        return 'Restarting: ' + checks + ' checks running, elapsed ' + elapsed;
      }

      function render(status) {
        lastStatus = status;
        const notice = status && status.notice;
        const files = notice && Array.isArray(notice.files) ? notice.files : [];
        // The inline `display:flex` beats the `hidden` attribute, so the notice
        // has to be hidden through the style itself: it used to stay on screen
        // with no text and a live "Restart now" button. An embedded task leaves
        // it to the window that holds it, where it is a bar and not a column.
        const showNotice = (Boolean(notice) || restarting) && !embedded;
        banner.hidden = !showNotice;
        banner.style.display = showNotice ? 'flex' : 'none';
        // One short line; the long reason and the file names live in the tooltip, not across the page.
        const detail = notice ? (notice.reason || 'A full restart is required to use the changed server code.') + ' Changed files: ' + (files.length ? files.join(', ') : 'not listed') + '.' : '';
        const waiting = status && status.checks_running > 0 ? status.checks_running + ' check' + (status.checks_running === 1 ? '' : 's') : 'running work';
        const seconds0 = Math.floor(Math.max(0, Number(status && status.elapsed_s) || 0));
        const minutes = Math.floor(seconds0 / 60);
        noticeText.textContent = restarting
          ? 'Restart is waiting for ' + waiting + ' to finish (' + (minutes ? minutes + ' min' : seconds0 + 's') + '). New tasks queue until then.'
          : (notice ? 'Newer server code is ready. Restart when you like.' : '');
        noticeText.title = detail;
        restartButton.hidden = restarting;
        cancelButton.hidden = !restarting;
        cancelButton.disabled = cancelling;
        restartButton.disabled = pending || restarting;
        const swaps = status && Array.isArray(status.swaps) ? status.swaps : [];
        const swap = swaps.length ? swaps[swaps.length - 1] : null;
        const successful = swap && (swap.ok === true || swap.success === true || swap.status === 'success' || swap.status === 'swapped');
        quiet.hidden = !swap;
        quiet.textContent = swap ? (successful ? 'swapped ' : 'Swap not confirmed: ') + (Array.isArray(swap.rows) ? swap.rows.join(', ') : String(swap.rows == null ? '' : swap.rows)) + (swap.swapped_at ? ' at ' + new Date(Number(swap.swapped_at) * 1000).toLocaleString() : '') : '';
        if (label) label.textContent = restarting ? progress(status) : buildLine;
        if (badge) {
          badge.hidden = false;
          badge.title = restarting ? progress(status) : 'Restart Thomas';
          badge.setAttribute('aria-label', restarting ? progress(status) : 'Restart Thomas');
        }
      }

      // A restart in the middle of a run cuts that run off, so the "newer code"
      // prompt waits until no Chat, Build or Work run is busy. The 30s refresh
      // re-checks it, so the prompt appears once the run has finished.
      function anyRunBusy() {
        const modes = window.ThomasUnifiedModes;
        if (!modes || typeof modes.isBusy !== 'function') return false;
        return ['chat', 'code', 'work'].some(mode => modes.isBusy(mode));
      }

      async function refreshBuildBadge() {
        try {
          const r = await fetch('/api/health', { cache: 'no-store' });
          if (!r.ok) return;
          const d = await r.json();
          const build = d && typeof d.build === 'object' && d.build ? d.build : { version: d && d.version };
          const parts = [':' + port];
          if (build.version) parts.push('v' + build.version);
          if (build.commit) parts.push(build.commit);
          if (build.stale === true && !anyRunBusy()) parts.push('Restart Thomas — newer code is available');
          if (build.dirty) parts.push('uncommitted');
          buildLine = parts.join(' · ');
          if (badge) {
            if (build.dirty) badge.setAttribute('data-dirty', '1');
            else badge.removeAttribute('data-dirty');
          }
          render(lastStatus);
        } catch (e) { /* Status polling handles a restarting server. */ }
      }

      async function pollStatus() {
        if (polling) return;
        polling = true;
        try {
          // The status rides on the health answer: the shell adds no routes, and this one is polled anyway.
          const response = await fetch('/api/health', { cache: 'no-store' });
          if (!response.ok) return;
          const health = await response.json();
          const status = health && typeof health === 'object' ? health.restart : null;
          if (!status || typeof status !== 'object') return;
          const nextGeneration = status.generation;
          if (generation != null && nextGeneration != null && nextGeneration !== generation) {
            window.location.reload();
            return;
          }
          if (status.restarting && !restarting) {
            restarting = true;
            previousGeneration = generation != null ? generation : nextGeneration;
          } else if (restarting && !status.restarting && !pending) {
            restarting = false;
            previousGeneration = null;
          }
          if (nextGeneration != null) generation = nextGeneration;
          render(status);
        } catch (e) {
          // Keep polling the same origin while the server is unavailable.
          if (restarting) render(lastStatus);
        } finally {
          polling = false;
        }
      }

      async function requestRestart() {
        if (pending || restarting) return;
        pending = true;
        render(lastStatus);
        try {
          // Establish the old generation before issuing a request that may stop the server.
          if (generation == null) await pollStatus();
          const response = await fetch('/api/server/restart', { method: 'POST', cache: 'no-store' });
          let data = null;
          try { data = await response.json(); } catch (e) { /* Invalid responses are not confirmation. */ }
          if (!response.ok || !data || data.ok !== true || data.restarting !== true) {
            if (response.status === 401 || response.status === 403) {
              const card = data && (data.card || data.approval_card);
              const showCard = deps.showProtectedApprovalCard || deps.showApprovalCard;
              if (card && typeof showCard === 'function') showCard(card);
              else if (label) label.textContent = 'Owner sign-in required to restart';
            } else if (label) label.textContent = 'Restart request failed';
            return;
          }
          previousGeneration = generation != null ? generation : (data.generation != null ? data.generation : null);
          if (generation == null) generation = previousGeneration;
          restarting = true;
          render(Object.assign({}, lastStatus || {}, data));
          pollStatus();
        } catch (e) {
          if (label) label.textContent = 'Restart request failed; try again';
        } finally {
          pending = false;
          restartButton.disabled = restarting;
        }
      }

      if (badge) {
        badge.setAttribute('role', 'button');
        badge.tabIndex = 0;
        badge.addEventListener('click', requestRestart);
        badge.addEventListener('keydown', event => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            requestRestart();
          }
        });
      }
      async function cancelRestart() {
        if (cancelling) return;
        cancelling = true;
        render(lastStatus);
        try {
          const response = await fetch('/api/server/restart/cancel', { method: 'POST', cache: 'no-store' });
          if (response.ok) { restarting = false; pending = false; previousGeneration = null; }
        } catch (e) { /* the next poll shows the real state */ }
        cancelling = false;
        await pollStatus();
      }

      restartButton.addEventListener('click', requestRestart);
      cancelButton.addEventListener('click', cancelRestart);
      render(null);
      refreshBuildBadge();
      pollStatus();
      setInterval(refreshBuildBadge, 30000);
      // Every 5 s while nothing is happening, every 2 s while a restart is under way, so the page follows it.
      (function schedule() { setTimeout(async () => { await pollStatus(); schedule(); }, restarting || pending ? 2000 : 5000); })();
    }
    // The shell historically calls this setupVersionCopy; keep both names usable.
    const setupVersionCopy = mountBuildBadge;
    return { botHTML, hydrateBots, avatar, applyTheme, selectTheme, toggleThemeMenu, renderThemeMenu, mountBuildBadge, setupVersionCopy };
  }
  window.ThomasChatThemeControls = { create };
})();
