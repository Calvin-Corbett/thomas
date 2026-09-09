
"use strict";

(function () {
  const policy = window.ThomasBrowserDocsPolicy;
  const LAST_CHAT = "thomas_last_chat";
  const LAST_SESSION = "thomas_last_session";
  const ROW_WAIT_MS = 15000;
  const LABELS = { chat: "Chat", code: "Build", work: "Work" };

  function wire(ctx) {
    const { rowWrap, asideEl, makeTab, byId, activate, setTitle, setStatus, getActiveId,
      getTabs, homeTab, keys, wsByLabel, openWorkspaceTab, faceFor, closeMenus } = ctx;
    const docs = [];
    const sidebar = { collapsed: false };
    let bootingFresh = 0;   // new-chat documents still booting: hold the reload keys

    function storage(fn) { try { return fn(localStorage); } catch (_) { return null; } }
    function docOf(tab) { try { return tab.frame ? tab.frame.contentDocument : null; } catch (_) { return null; } }
    function winOf(tab) { try { return tab.frame ? tab.frame.contentWindow : null; } catch (_) { return null; } }
    function shellOf(doc) { return doc ? doc.getElementById("tc-shell") : null; }
    function under(e, sel) { const t = e.target; return t && typeof t.closest === "function" ? t.closest(sel) : null; }

    /* ── What a document says about itself ───────────────────────────── */
    function isBusy(doc, mode) {
      const btn = doc && doc.querySelector('.tc-mode-button[data-thomas-mode="' + mode + '"]');
      return Boolean(btn && btn.hasAttribute("data-running"));
    }
    function selectedRow(doc, mode) {
      if (!doc) return null;
      if (mode === "chat") {
        return Array.from(doc.querySelectorAll("#tc-chats [data-history-id]"))
          .find(r => (r.getAttribute("style") || "").indexOf("--c-surface-2") >= 0) || null;
      }
      return doc.querySelector("#tc-chats [data-history-id].is-active");
    }
    function hasContent(tab, doc) {
      if (tab.mode !== "chat") return Boolean(selectedRow(doc, tab.mode));
      const thread = doc && doc.getElementById("tc-thread");
      return Boolean(thread && thread.childElementCount);
    }
    function surfaceState(tab, doc) {
      const input = doc && doc.getElementById("tc-input");
      return {
        mode: tab.mode, chatId: tab.chatId || "", busy: isBusy(doc, tab.mode),
        draft: input ? input.value : "", hasContent: hasContent(tab, doc),
      };
    }
    function rowIds(doc) {
      return new Set(Array.from(doc.querySelectorAll("#tc-chats [data-history-id]")).map(r => r.dataset.historyId));
    }
    // A tab's identity is observed, never assumed: the row the document marks
    // as selected is the conversation it holds. A conversation born on this
    // surface never gets a selected row (chat.html leaves activeChat null after
    // the first turn), so a held id survives as long as the thread has content.
    function learn(tab, doc) {
      if (tab.missing) return;
      const row = selectedRow(doc, tab.mode);
      if (!row && tab.chatId && hasContent(tab, doc)) return;
      const id = row ? row.dataset.historyId : "";
      if (id === (tab.chatId || "")) return;
      tab.chatId = id;
      setTitle(tab, (row && row.dataset.historyTitle) || LABELS[tab.mode]);
      if (tab === homeTab) writeReloadTarget();
    }
    // The first turn on a blank surface creates a conversation that the list
    // shows but never marks: the one row that was not there when the turn began.
    function resolveFresh(tab, doc) {
      if (!tab.awaitingNew || !tab.rowsAtStart) return;
      const fresh = Array.from(rowIds(doc)).filter(id => !tab.rowsAtStart.has(id));
      if (fresh.length !== 1) return;
      const row = doc.querySelector('#tc-chats [data-history-id="' + CSS.escape(fresh[0]) + '"]');
      tab.awaitingNew = false; tab.chatId = fresh[0];
      setTitle(tab, (row && row.dataset.historyTitle) || LABELS[tab.mode]);
      if (tab === homeTab) writeReloadTarget();
    }

    /* ── Reload target: a reload of / comes back to what home held, or to the
       conversation you used most recently in a tab when home holds nothing. Every
       document's selectChat writes these keys, so the shell writes them last.
       It never REMOVES them: with nothing to name, chat.html's own values stand. ── */
    function reloadTarget() {
      if (homeTab.chatId) return homeTab.chatId;
      const recent = docs.filter(t => t.mode === "chat" && t.chatId)
        .sort((a, b) => (b.activatedAt || 0) - (a.activatedAt || 0))[0];
      return recent ? recent.chatId : "";
    }
    function writeReloadTarget() {
      if (bootingFresh > 0) return;   // a new chat is reading these keys right now
      const id = reloadTarget();
      if (!id) return;
      storage(ls => { ls.setItem(LAST_CHAT, id); ls.setItem(LAST_SESSION, id); });
    }

    /* ── Interceptors: the same question from every document ──────────── */
    // A click we swallow would have closed whatever menu was open; close it.
    function stop(e, doc) {
      e.preventDefault(); e.stopPropagation();
      if (closeMenus) closeMenus();
      const history = doc && doc.defaultView && doc.defaultView.ThomasSidebarHistory;
      if (history && history.closeMenu) history.closeMenu();
    }
    function onRowClick(tab, doc, e) {
      const row = under(e, "#tc-chats [data-history-id]");
      if (!row || tab.suppress) return;
      if (e.type === "auxclick" && e.button !== 1) return;
      const spec = { id: row.dataset.historyId, mode: row.dataset.historyMode || tab.mode, title: row.dataset.historyTitle || "" };
      const d = policy.decideRowClick({ surface: surfaceState(tab, doc), row: spec, tabs: getTabs(),
        modifiers: { ctrl: e.ctrlKey, meta: e.metaKey, middle: e.type === "auxclick" } });
      if (d.action === "adopt") { setTimeout(() => learn(tab, doc), 0); return; }
      stop(e, doc);
      if (d.action === "focus") activate(d.tab.id);
      else open({ mode: spec.mode, chatId: spec.id, title: spec.title });
    }
    function installOn(tab, doc) {
      doc.addEventListener("click", e => onRowClick(tab, doc, e), true);
      doc.addEventListener("auxclick", e => onRowClick(tab, doc, e), true);
      doc.addEventListener("click", e => {
        const btn = under(e, ".tc-mode-button[data-thomas-mode]"); if (!btn) return;
        const mode = btn.dataset.thomasMode;
        // Home is the pinned Chat tab: when it was carried into another mode
        // (a restored surface, a deep link), Chat brings it back by itself.
        if (tab === homeTab && mode === "chat" && homeTab.mode !== "chat") return;
        stop(e, doc);
        const d = policy.decideModeClick({ mode, home: homeTab, tabs: getTabs() });
        if (d.action === "focus") activate(d.tab.id); else open({ mode: d.mode });
      }, true);
      doc.addEventListener("keydown", e => {
        if (!under(e, ".tc-mode-button[data-thomas-mode]")) return;
        if (["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(e.key) >= 0) stop(e);
      }, true);
      doc.addEventListener("click", e => {
        if (!under(e, "#tc-newchat")) return;
        const d = policy.decideNewChat({ surface: surfaceState(tab, doc) });
        if (d.action === "adopt") { setTimeout(() => learn(tab, doc), 0); return; }
        stop(e, doc); open({ mode: d.mode });
      }, true);
      doc.addEventListener("click", e => {
        if (!under(e, "#tc-settings")) return;
        stop(e, doc); openWorkspaceTab("settings");
      }, true);
      if (tab !== homeTab) doc.addEventListener("click", e => {
        const btn = under(e, "#tc-workspaces button"); if (!btn) return;
        const mode = wsByLabel[(btn.textContent || "").trim()]; if (!mode) return;
        stop(e, doc); openWorkspaceTab(mode);
      }, true);
      // Busy per document: the mode button carries data-running for its mode.
      const sw = doc.getElementById("tc-mode-switch");
      if (sw) new MutationObserver(() => {
        const busy = isBusy(doc, tab.mode);
        if (busy && tab.status !== "working") {
          setStatus(tab, "working");
          if (!tab.chatId) tab.rowsAtStart = rowIds(doc);
        } else if (!busy && tab.status === "working") {
          setStatus(tab, "done");
          if (!tab.chatId && tab.rowsAtStart) {
            tab.awaitingNew = true;
            setTimeout(() => { tab.awaitingNew = false; }, 15000);
          }
          setTimeout(() => { learn(tab, doc); resolveFresh(tab, doc); }, 0);
        }
      }).observe(sw, { attributes: true, subtree: true, attributeFilter: ["data-running"] });
      const chats = doc.getElementById("tc-chats");
      if (chats) new MutationObserver(() => { learn(tab, doc); resolveFresh(tab, doc); })
        .observe(chats, { childList: true, subtree: true, attributes: true, attributeFilter: ["style", "class"] });
      const shell = shellOf(doc);
      if (shell && tab === homeTab) new MutationObserver(() => {
        const mode = shell.dataset.surfaceMode || "chat";
        if (mode === tab.mode) return;
        tab.mode = mode; tab.chatId = ""; tab.missing = false;
        setTitle(tab, LABELS[mode]);
        learn(tab, doc);
      }).observe(shell, { attributes: true, attributeFilter: ["data-surface-mode"] });
      // The page may have restored its conversation before this ran (home boots
      // before the chrome attaches), and an observer only sees what changes next.
      learn(tab, doc);
      // Home is the pinned Chat tab. A surface restored into Build by the last
      // session belongs in a Build tab now; only an explicit deep link keeps it.
      if (tab === homeTab && shell && shell.dataset.surfaceMode !== "chat"
        && !/[?&]forge_code=/.test(location.search) && doc.defaultView.ThomasUnifiedModes) {
        try { doc.defaultView.ThomasUnifiedModes.setMode("chat"); } catch (_) { /* the observer keeps the truth */ }
      }
      sidebar.collapsed = sidebarCollapsed(doc);
    }

    /* ── Opening and wiring a document tab ────────────────────────────── */
    function waitForRow(doc, id) {
      return new Promise(resolve => {
        const find = () => doc.querySelector(id ? '#tc-chats [data-history-id="' + CSS.escape(id) + '"]' : "#tc-chats [data-history-id]");
        const now = find(); if (now) return resolve(now);
        const wrap = doc.getElementById("tc-chats");
        if (!wrap) return resolve(null);
        let mo = null;
        const timer = setTimeout(() => { if (mo) mo.disconnect(); resolve(null); }, ROW_WAIT_MS);
        mo = new MutationObserver(() => { const r = find(); if (r) { clearTimeout(timer); mo.disconnect(); resolve(r); } });
        mo.observe(wrap, { childList: true, subtree: true });
      });
    }
    async function settle(tab, doc) {
      const row = await waitForRow(doc, tab.chatId);
      if (!row) { tab.missing = true; setStatus(tab, "error"); setTitle(tab, "Not in the list"); return false; }
      // Compare identities: the child's own restore re-renders the list between
      // the row appearing and this continuation, so the element may be stale.
      const sel = selectedRow(doc, tab.mode);
      if (sel && sel.dataset.historyId === tab.chatId) return true;
      const fresh = doc.querySelector('#tc-chats [data-history-id="' + CSS.escape(tab.chatId) + '"]') || row;
      tab.suppress = true;
      try { fresh.click(); } finally { setTimeout(() => { tab.suppress = false; }, 0); }
      return true;
    }
    function sidebarCollapsed(doc) {
      const shell = shellOf(doc);
      return Boolean(shell && shell.style.getPropertyValue("--sidebar-margin").trim() === "-280px");
    }
    function clickSidebarToggle(doc) {
      const btn = doc && doc.getElementById("tc-sidebar-toggle");
      if (btn) btn.click();
    }
    async function wireDoc(tab) {
      const doc = docOf(tab), win = winOf(tab);
      if (!doc || !win || !shellOf(doc)) { setStatus(tab, "error"); return; }
      if (tab.mode !== "chat" && shellOf(doc).dataset.surfaceMode !== tab.mode && win.ThomasUnifiedModes) {
        try { await win.ThomasUnifiedModes.setMode(tab.mode); } catch (_) { /* the mode buttons stay honest */ }
      }
      let found = true;
      if (tab.chatId && tab.mode !== "code") found = await settle(tab, doc);
      // A new chat must be new. The child's boot restores whatever the reload
      // keys name once its list has rendered, so wait for the list, give the
      // restore its turn, and undo it if it happened.
      if (tab.mode === "chat" && !tab.chatId) {
        await waitForRow(doc, "");
        await new Promise(r => setTimeout(r, 120));
        if (selectedRow(doc, "chat")) {
          const fresh = doc.getElementById("tc-newchat");
          if (fresh) { tab.suppress = true; try { fresh.click(); } finally { setTimeout(() => { tab.suppress = false; }, 0); } }
        }
        if (tab.freshBoot) { tab.freshBoot = false; bootingFresh = Math.max(0, bootingFresh - 1); }
      }
      installOn(tab, doc);
      // A document applies the theme it PARSED with at the end of its own boot,
      // so one that finished booting after a theme change lands on the old one
      // while the strip and every other document show the new. The shell's
      // current theme is the truth; assert it once the document is up, and
      // again next frame in case its boot is still running.
      assertTheme(tab);
      if (keys && keys.attachTo) keys.attachTo(win);
      if (sidebar.collapsed !== sidebarCollapsed(doc)) clickSidebarToggle(doc);
      tab.ready = true;
      tab.frame.classList.add("is-ready");
      pauseWorld(tab, getActiveId() !== tab.id);
      if (getActiveId() === tab.id) show(tab);
      setStatus(tab, isBusy(doc, tab.mode) ? "working" : "idle");
      if (found) learn(tab, doc);
      writeReloadTarget();
    }
    function open(spec) {
      const mode = spec.mode === "code" || spec.mode === "work" ? spec.mode : "chat";
      const held = spec.chatId && getTabs().find(t => t.mode === mode && t.chatId === spec.chatId && (t.kind === "doc" || t === homeTab));
      if (held) { activate(held.id); return held; }
      const title = spec.title || LABELS[mode];
      const tab = makeTab({ kind: "doc", mode, chatId: spec.chatId || "", title, face: faceFor(mode),
        url: "thomas://" + mode + (spec.chatId ? "/" + spec.chatId : "") });
      tab.ready = false; tab.suppress = false;
      setStatus(tab, "working");
      // The child restores whatever thomas_last_chat names at its boot, so
      // name THIS conversation; settle() corrects a lost race, and the reload
      // target is written back to home's conversation once the child is up.
      // The child restores whatever the reload keys name at its boot, so name THIS
      // conversation, or nothing at all for a new chat; wireDoc writes home's
      // target back once the child is up.
      if (mode === "chat") storage(ls => {
        if (spec.chatId) ls.setItem(LAST_CHAT, spec.chatId);
        else { ls.removeItem(LAST_CHAT); ls.removeItem(LAST_SESSION); }
      });
      if (mode === "chat" && !spec.chatId) { tab.freshBoot = true; bootingFresh += 1; }
      const frame = document.createElement("iframe");
      frame.className = "bt-doc";
      frame.title = title;
      frame.inert = true;
      frame.setAttribute("aria-hidden", "true");
      frame.addEventListener("load", () => {
        wireDoc(tab).catch(() => {
          setStatus(tab, "error");
          if (tab.freshBoot) { tab.freshBoot = false; bootingFresh = Math.max(0, bootingFresh - 1); }
        });
      });
      frame.src = policy.docUrlFor({ mode, chatId: spec.chatId });
      rowWrap.appendChild(frame);
      tab.frame = frame;
      docs.push(tab);
      activate(tab.id);
      return tab;
    }

    /* ── Show and hide: the only thing a switch ever does ─────────────── */
    function pauseWorld(tab, paused) {
      const doc = docOf(tab);
      if (doc && doc.documentElement) doc.documentElement.classList.toggle("bt-doc-hidden", paused);
    }
    function hideAll() {
      docs.forEach(t => {
        t.frame.classList.remove("is-active"); t.frame.inert = true; t.frame.setAttribute("aria-hidden", "true");
        pauseWorld(t, true);
      });
      asideEl.inert = true;
    }
    function show(tab) {
      tab.frame.classList.add("is-active"); tab.frame.inert = false; tab.frame.removeAttribute("aria-hidden");
      pauseWorld(tab, false);
      tab.activatedAt = Date.now();
      const doc = docOf(tab);
      if (tab.ready && doc && (!doc.activeElement || doc.activeElement === doc.body)) {
        const input = doc.getElementById("tc-input"); if (input) setTimeout(() => input.focus(), 40);
      }
    }
    function remove(tab) {
      const i = docs.indexOf(tab); if (i >= 0) docs.splice(i, 1);
      if (tab.freshBoot) { tab.freshBoot = false; bootingFresh = Math.max(0, bootingFresh - 1); }
      if (tab.frame) tab.frame.remove();
    }
    function reload(tab) {
      tab.ready = false; tab.frame.classList.remove("is-ready"); setStatus(tab, "working");
      if (tab.mode === "chat" && tab.chatId) storage(ls => ls.setItem(LAST_CHAT, tab.chatId));
      tab.frame.src = policy.docUrlFor({ mode: tab.mode, chatId: tab.chatId });
    }
    // One sidebar state for every document: the bookmarks-bar toggle folds
    // home through its own handler and every tab document through theirs.
    function onSidebarToggle() {
      sidebar.collapsed = !sidebar.collapsed;
      docs.forEach(t => { if (t.ready && sidebarCollapsed(docOf(t)) !== sidebar.collapsed) clickSidebarToggle(docOf(t)); });
    }

    /* ── Theme relay: drive each document's own switcher ──────────────── */
    function pickTheme(tab, name) {
      const doc = docOf(tab), win = winOf(tab);
      const shell = shellOf(doc); if (!shell || !win || shell.dataset.theme === name) return;
      const btn = doc.getElementById("tc-theme-btn"); if (!btn) return;
      btn.click();                                   // renders #tc-theme-options
      const themes = (win.ThomasChatThemes && win.ThomasChatThemes.THEMES) || {};
      const keys = Object.keys(themes);
      const options = Array.from(doc.querySelectorAll("#tc-theme-options button"));
      let opt = keys.length === options.length ? options[keys.indexOf(name)] : null;
      const label = (themes[name] || {}).name || name;
      if (!opt) opt = options.find(b => (b.textContent || "").indexOf(label) >= 0) || null;
      if (opt) opt.click(); else btn.click();       // no match: close what we opened
    }
    // The shell owns the theme. A document applies the one it PARSED with at
    // the end of its own boot, which can land after a theme change and leave
    // it on the old theme while the strip and every other document show the
    // new one. So assert the shell's theme and keep checking, briefly and a
    // bounded number of times, until the document agrees.
    function assertTheme(tab, tries) {
      const here = document.getElementById("tc-shell");
      const name = here && here.dataset ? here.dataset.theme : "";
      if (!name) return;
      pickTheme(tab, name);
      const left = typeof tries === "number" ? tries : 8;
      if (left <= 0) return;
      setTimeout(() => {
        const doc = tab.frame && tab.frame.contentDocument;
        const shell = doc && doc.getElementById("tc-shell");
        if (shell && shell.dataset.theme !== name) assertTheme(tab, left - 1);
      }, 80);
    }
    window.addEventListener("thomas:themechange", e => {
      const name = e.detail && e.detail.theme; if (!name) return;
      // Bounded re-assertion, not a single click: a document whose own boot
      // finishes just after this would otherwise settle on the old theme.
      docs.forEach(t => assertTheme(t));
    });
    window.addEventListener("pagehide", writeReloadTarget);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") writeReloadTarget(); });

    return { open, hideAll, show, remove, reload, installOn, onSidebarToggle, learn, list: () => docs.slice() };
  }

  window.ThomasBrowserDocs = { wire };
}());
