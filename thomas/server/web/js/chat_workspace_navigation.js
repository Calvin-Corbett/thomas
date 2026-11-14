/* Chat workspace navigation. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {

    // Workspaces keep their OWN existing UI — open them in the preserved SPA,
    // Bounded standalone routes avoid the full classic runtime. Compatible
    // deep links remain while the other owner lanes are separated.
    const WORKSPACE_ROUTES = {
      my_stuff: '/my-stuff?embed=1',
      settings: '/settings?embed=1',
      // System replaced the Agents page, which had replaced Mission Control, System Map and Agent Ops. The old
      // address still answers with the System page, so a saved link or an older redirect lands there. It styles
      // itself from tokens.css alone, so it belongs in the MODERN list rather than behind /classic.
      agents: '/agents?embed=1',
      system: '/system?embed=1',
    };

    const CLASSIC_WORKSPACE_ROUTE = '/classic?embed=1';

    function workspaceFrame(mode) {
      if (!WORKSPACE_ROUTES[mode]) return document.getElementById('tc-ws-frame');
      let frame = document.getElementById('tc-direct-frame');
      if (frame) return frame;
      frame = document.createElement('iframe'); frame.id = 'tc-direct-frame'; frame.className = 'tc-workspace-frame'; frame.title = 'Workspace';
      frame.style.cssText = 'display:none;position:absolute;inset:0;width:100%;height:100%;border:0;z-index:20;background:var(--c-bg);background:color-mix(in srgb, var(--c-bg) 82%, transparent);backdrop-filter:blur(22px);-webkit-backdrop-filter:blur(22px);';
      document.getElementById('tc-body-row').appendChild(frame); return frame;
    }

    function syncWorkspaceFrame(frame) {
      const theme = deps.THEMES[deps.state.theme];
      if (theme && window.ThomasWorkspaceShell) window.ThomasWorkspaceShell.sendTheme(frame, deps.state.theme, theme.vars);
      if (frame.contentWindow && frame.dataset.workspaceMode && !WORKSPACE_ROUTES[frame.dataset.workspaceMode]) {
        frame.contentWindow.postMessage({ type: "thomas:workspace:navigate", mode: frame.dataset.workspaceMode }, location.origin);
      }
    }

    function openWorkspace(mode) {
      const f = workspaceFrame(mode);
      if (!f) return;
      const route = WORKSPACE_ROUTES[mode] || CLASSIC_WORKSPACE_ROUTE;
      document.querySelectorAll('.tc-workspace-frame').forEach((frame) => { frame.style.display = 'none'; });
      f.dataset.workspaceMode = mode;
      // An old-style page is switched by message; it stays out of sight until it shows the page asked for.
      if (route === CLASSIC_WORKSPACE_ROUTE && window.ThomasWorkspaceShell) window.ThomasWorkspaceShell.arrive(f, mode);
      f.onload = () => syncWorkspaceFrame(f);
      if (f.dataset.route !== route) {
        f.dataset.route = route;
        f.src = route;
      } else syncWorkspaceFrame(f);
      f.style.display = 'block';
      const primary = document.getElementById('tc-primary-column');
      const canvasPanel = document.getElementById('tc-canvas');
      if (primary) { primary.style.visibility = 'hidden'; primary.inert = true; }
      if (canvasPanel) { canvasPanel.style.visibility = 'hidden'; canvasPanel.inert = true; }
      deps.state.workspaceOpen = true;
      if (window.ThomasWorkspaceChat) window.ThomasWorkspaceChat.setWorkspace(mode);
    }

    function showChat() {
      document.querySelectorAll('.tc-workspace-frame').forEach((frame) => { frame.style.display = 'none'; });
      const primary = document.getElementById('tc-primary-column');
      const canvasPanel = document.getElementById('tc-canvas');
      if (primary) { primary.style.visibility = ''; primary.inert = false; }
      if (canvasPanel) { canvasPanel.style.visibility = ''; canvasPanel.inert = false; }
      deps.state.workspaceOpen = false;
      if (window.ThomasWorkspaceChat) window.ThomasWorkspaceChat.setWorkspace(null);
    }

    function stageUiAiEdit(event) {
      const detail = event && event.detail || {};
      if (!detail.identity || !detail.prompt) return;
      if (deps.state.workspaceOpen && window.ThomasWorkspaceChat) {
        window.ThomasWorkspaceChat.open({ draft: `Update ${detail.label || detail.identity} (${detail.identity}): ${detail.prompt}` });
        return;
      }
      // The standard sends an AI edit to the ACTIVE surface's Thomas. Calling
      // showChat() unconditionally threw you out of Code and into Chat, so
      // asking Code to change its own region both lost your place and handed
      // the request to the dispatcher instead of to the one that builds.
      const codeInput = deps.state.surfaceMode === 'code' ? document.getElementById('tc-input') : null;
      if (codeInput) {
        codeInput.value = `Update ${detail.label || detail.identity} (${detail.identity}): ${detail.prompt}`;
        codeInput.dispatchEvent(new Event('input', { bubbles: true }));
        codeInput.focus();
        return;
      }
      showChat();
      deps.state.input = `In ${detail.workspace || 'this workspace'}, update ${detail.label || detail.identity} (${detail.identity}): ${detail.prompt}`;
      deps.inputEl.value = deps.state.input; deps.autosize(); deps.inputEl.focus();
    }

    // ---------- Plugin workspace host ----------
    // A marketplace plugin can claim a left-nav workspace. It declares the whole
    // contract itself: mode_id, surface_url, surface_mode, icon,
    // left_nav_behavior and default_nav_order. Hosting one is just reading that
    // and pointing the modern workspace frame at its surface -- these are
    // self-contained pages, so they need none of the legacy shell.
    let pluginWorkspaces = [];
    // Which of Thomas's own five workspaces you have uninstalled. The server keeps the list (it arrives with the
    // installed plugins); the copy in this browser only stops an uninstalled row flashing before that answer.
    const REMOVED_KEY = 'thomas.workspaces.uninstalled.v1';
    let removedStock = [];
    try { removedStock = (JSON.parse(localStorage.getItem(REMOVED_KEY) || '[]') || []).map(String); } catch (_) { removedStock = []; }
    function setRemovedStock(list) {
      removedStock = list.map(String);
      try { localStorage.setItem(REMOVED_KEY, JSON.stringify(removedStock)); } catch (_) { /* the server has it */ }
    }


    // Plugins name their icon in Phosphor terms; the shell draws its own. An
    // unmapped name must not fall through to nothing, so anything unrecognised
    // gets the marketplace glyph rather than an empty button.
    // Keyed WITHOUT the ph- prefix on purpose. Writing the full Phosphor names
    // here put literal ph-* strings in this shell, and the icon contract scans
    // the shell for exactly that -- a ph- name absent from the drawn icon map
    // renders as a bare dot, which has shipped as a real-looking control before.
    // These are lookup keys, not icons the page uses, so the prefix is stripped
    // at the call site instead.
    const PLUGIN_ICON_GLYPHS = {
      'chart-line-up': 'trading', 'chart-line': 'trading', 'currency-dollar': 'trading',
      'users': 'office', 'user': 'office', 'buildings': 'office',
      'palette': 'canvas', 'chat': 'channels', 'coins': 'tokens',
      'books': 'library', 'gear': 'settings',
    };


    async function loadPluginWorkspaces() {
      try {
        const res = await fetch('/api/marketplace/installed', { cache: 'no-store' });
        if (!res.ok) return;
        const body = await res.json();
        const rows = Array.isArray(body && body.plugins) ? body.plugins : [];
        if (Array.isArray(body && body.removed_workspaces)) setRemovedStock(body.removed_workspaces);
        pluginWorkspaces = rows
          .filter(p => p && p.enabled && p.surface_url && p.mode_id
                       && String(p.left_nav_behavior || 'workspace') === 'workspace')
          .sort((a, b) => Number(a.default_nav_order || 999) - Number(b.default_nav_order || 999))
          .map(p => {
            const mode = String(p.mode_id);
            // Register the surface so openWorkspace() takes the MODERN direct
            // frame instead of falling through to /classic.
            WORKSPACE_ROUTES[mode] = String(p.surface_url);
            return {
              icon: PLUGIN_ICON_GLYPHS[String(p.icon || '').replace(/^ph-/, '')] || 'market',
              label: String(p.surface_title || p.display_name || mode),
              mode,
              // What the row's menu uninstalls. A built-in workspace has none: it ships with Thomas.
              pluginId: String(p.plugin_id || ''),
            };
          });
        renderWorkspaces(); // also when the list is now empty: the last plugin may just have been uninstalled
      } catch (error) {
        // A marketplace that cannot be read must not cost you the built-in
        // workspaces: the static list has already rendered by now.
      }
    }

    // Uninstall from the row's menu (chat_workspace_arrange.js asks; this file is the one that talks to the server).
    // It is the same uninstall Marketplace does: the plugin's code is removed, what you made with it is kept in
    // .thomas/plugin-data, and Marketplace offers it again. The line under the list says which of those happened.
    let workspaceNotice = '';
    async function uninstallWorkspace(detail) {
      const pluginId = String(detail && detail.pluginId || '');
      const name = String(detail && detail.label || pluginId);
      if (!pluginId) return;
      let failed = '';
      try {
        const res = await fetch(`/api/marketplace/plugins/${encodeURIComponent(pluginId)}/uninstall`, { method: 'POST' });
        const body = await res.json().catch(() => ({}));
        if (!res.ok || !body.ok) failed = String(body.error || `the server answered ${res.status}`);
      } catch (error) {
        failed = 'Thomas could not be reached';
      }
      workspaceNotice = failed
        ? `${name} was not uninstalled: ${failed}.`
        : `${name} is uninstalled. What you made with it is kept. Install it again from Marketplace.`;
      if (!failed) {
        if (pluginId === `thomas-${detail.mode}`) setRemovedStock(removedStock.concat(detail.mode));
        else { pluginWorkspaces = pluginWorkspaces.filter((w) => w.mode !== detail.mode); delete WORKSPACE_ROUTES[detail.mode]; }
        const shown = [...document.querySelectorAll('.tc-workspace-frame')]
          .some((frame) => frame.dataset.workspaceMode === detail.mode && frame.style.display !== 'none');
        if (shown) showChat();
        window.dispatchEvent(new CustomEvent('thomas:workspace:uninstalled', { detail: { mode: detail.mode } }));
      }
      renderWorkspaces(); // now, so the line shows even if the list cannot be read again
      await loadPluginWorkspaces();
    }
    window.addEventListener('thomas:workspace:uninstall', (event) => { void uninstallWorkspace(event.detail); });
    // Installing or uninstalling in Marketplace happens inside its own page, which tells this one nothing. So the list
    // is read again when the pointer comes back to it, at most once every three seconds.
    let listReadAt = 0;
    document.addEventListener('pointerover', (event) => {
      if (!event.target.closest || !event.target.closest('#tc-workspaces') || Date.now() - listReadAt < 3000) return;
      listReadAt = Date.now();
      void loadPluginWorkspaces();
    });


    function renderWorkspaces() {
      const workspaces = [
        // Build and Work are first-class modes above search. Do not duplicate their
        // legacy Forge/Workforce entry points in this secondary workspace list.
        // Icons are drawn (ThomasIcons); the ph-* names here were Unicode
        // stand-ins — Library rendered as "▤", Mission Control as "⊕".
        // Agents reuses the 'mission' glyph. ThomasIcons draws a fixed set of glyphs and an unlisted name renders
        // nothing at all, silently, so a new surface has to share one; this one is free now that Mission Control,
        // System Map and Agent Ops are gone from this list. A dedicated glyph in thomas_icons.js is the real fix.
        // System: what Thomas is doing and how he is, a page at a time (system.html). It shares the 'mission' glyph.
        { icon: 'mission',  label: 'System',          mode: 'system' },
        { icon: 'office',   label: 'Virtual Office',  mode: 'office' },
        // Canvas is not listed: you said "It says canvas. We removed the canvas thing from Thomas" (2026-11-09).
        { icon: 'library',  label: 'Library',         mode: 'my_stuff' },
        { icon: 'channels', label: 'Channels',        mode: 'channels' },
        { icon: 'tokens',   label: 'Token Economy',   mode: 'token_economy' },
        { icon: 'market',   label: 'Marketplace',     mode: 'marketplace' },
      ].filter((w) => !removedStock.includes(w.mode))
        // Each of these is a plugin too, with a Marketplace id, so its row can uninstall it. Marketplace has none:
        // it is where the others are installed again.
        .map((w) => (w.mode === 'marketplace' ? w : Object.assign({ pluginId: `thomas-${w.mode}` }, w)));
      // Installed plugins that ask to be workspaces. Paper Trading used to be
      // hardcoded here and opened through /classic; it is a marketplace plugin
      // and already declares everything needed to place itself -- mode_id,
      // surface_url, icon, left_nav_behavior and default_nav_order. The legacy
      // shell read that contract and the modern one never did, which is why
      // Workforce was installed and enabled with a live surface and no way in.
      workspaces.push(...pluginWorkspaces);
      const wrap = document.getElementById('tc-workspaces');
      // Order, names and removals you chose (drag a row, or right-click it) are
      // applied here and kept in the browser; see chat_workspace_arrange.js.
      const arrangeApi = window.ThomasWorkspaceArrange;
      const shown = arrangeApi ? arrangeApi.arrange(workspaces) : workspaces;
      wrap.innerHTML = '';
      shown.forEach(w => {
        const b = document.createElement('button');
        b.className = 'hv-soft';
        b.dataset.mode = w.mode;
        b.dataset.defaultLabel = w.defaultLabel || w.label;
        if (w.pluginId) b.dataset.pluginId = w.pluginId;
        b.draggable = true;
        b.style.cssText = `width: 100%; display: flex; align-items: center; gap: 10px; padding: 9px 11px; margin-bottom: 1px; border-radius: 10px; border: 1px solid transparent; background: transparent; color: var(--c-dim); font-family: inherit; font-size: 13.5px; font-weight: 500; cursor: pointer; transition: all .14s;`;
        const mark = window.ThomasIcons ? window.ThomasIcons.glyph(w.icon, 17) : '';
        b.innerHTML = `${mark}<span>${deps.esc(w.label)}</span>`;
        b.addEventListener('click', () => openWorkspace(w.mode));
        wrap.appendChild(b);
      });
      if (arrangeApi) {
        arrangeApi.footer(wrap, workspaces, renderWorkspaces);
        arrangeApi.attach(wrap, renderWorkspaces);
      }
      if (workspaceNotice) {
        const note = document.createElement('div');
        note.className = 'tc-ws-notice';
        note.setAttribute('role', 'status');
        note.style.cssText = 'padding: 8px 11px; font-size: 12px; line-height: 1.45; color: var(--c-dim);';
        note.textContent = workspaceNotice;
        wrap.appendChild(note);
      }
    }
    return { workspaceFrame, syncWorkspaceFrame, openWorkspace, showChat, stageUiAiEdit, loadPluginWorkspaces, renderWorkspaces };
  }
  window.ThomasChatWorkspaceNavigation = { create };
})();
