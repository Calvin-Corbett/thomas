/* browser_shell_docs.js — a tab is a document that is only ever hidden.
 *
 * Calvin's invariant (2026-09-01): one live DOM per tab. Switching shows and
 * hides persistent containers; drafts, scroll and in-flight streams survive;
 * nothing re-mounts on a switch. chat.html cannot give a second conversation
 * its own thread (selectChat wipes #tc-thread and aborts the stream, and the
 * file is beyond the monolith limit so it cannot change), so every extra
 * Chat, Build or Work tab is a second chat.html document in an iframe. The
 * top-level page stays the home tab and is never driven by the strip again.
 *
 * Hidden means visibility:hidden + inert on the frame and a paused living
 * world inside it — never display:none (which drops the child's layout and
 * scroll) and never a DOM move (which reloads an iframe).
 *
 * Three facts about chat.html this module reads, all verified on dev at
 * 9933a233: the selected sidebar row carries background var(--c-surface-2)
 * inline (renderChats); a Code row carries class is-active; the mode button
 * for a running mode carries data-running (unified_mode_shell.updateChrome).
 */
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
      const code = tab.mode === "code" && doc.defaultView && doc.defaultView.ThomasCodeMode;
      const id = code && code.conversationId ? code.conversationId() : row ? row.dataset.historyId : "";
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
    async function settle(tab, doc, current) {
      const row = await waitForRow(doc, tab.chatId);
      if (!current()) return false;
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
    async function wireDoc(tab, doc, win, current) {
      if (shellOf(doc).dataset.surfaceMode !== tab.mode && win.ThomasUnifiedModes) {
        try { await win.ThomasUnifiedModes.setMode(tab.mode); } catch (_) { /* the mode buttons stay honest */ }
      }
      if (!current()) return false;
      if (shellOf(doc).dataset.surfaceMode !== tab.mode) {
        setStatus(tab, "error");
        if (!tab.loadErrorTitle) tab.loadErrorTitle = tab.title;
        setTitle(tab, "Could not open " + LABELS[tab.mode]);
        if (tab.freshBoot) { tab.freshBoot = false; bootingFresh = Math.max(0, bootingFresh - 1); }
        return false;
      }
      let found = true;
      if (tab.chatId && tab.mode === "code" && win.ThomasCodeMode) {
        try { await win.ThomasCodeMode.openConversation(tab.chatId, { withinTab: true }); }
        catch (_) {
          if (current()) { setStatus(tab, "error"); setTitle(tab, "Could not open Build"); }
          return false;
        }
      }
      if (tab.chatId && tab.mode !== "code") found = await settle(tab, doc, current);
      if (!current()) return false;
      // A new chat must be new. The child's boot restores whatever the reload
      // keys name once its list has rendered, so wait for the list, give the
      // restore its turn, and undo it if it happened.
      if (tab.mode === "chat" && !tab.chatId) {
        // Explicit child addresses never restore a different tab's conversation.
        // Older cached pages expose their boot promise instead of an arbitrary
        // history-row timeout (an empty history is a valid ready state).
        if (!win.ThomasChatBoot && win.ThomasChatReady) await win.ThomasChatReady;
        if (!current()) return false;
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
      if (tab.loadErrorTitle) { setTitle(tab, tab.loadErrorTitle); tab.loadErrorTitle = ""; }
      tab.ready = true;
      tab.frame.classList.add("is-ready");
      if (tab.loader) { tab.loader.remove(); tab.loader = null; }
      pauseWorld(tab, getActiveId() !== tab.id);
      if (getActiveId() === tab.id) show(tab);
      setStatus(tab, isBusy(doc, tab.mode) ? "working" : "idle");
      if (found) learn(tab, doc);
      writeReloadTarget();
    }
    function prepareDoc(tab) {
      if (!docs.includes(tab)) return Promise.resolve(false);
      const doc = docOf(tab), win = winOf(tab);
      if (doc && doc === tab.reloadingDocument) return Promise.resolve(false);
      if (tab.wiredDocument === doc && tab.wiring) return tab.wiring;
      tab.ready = false; tab.frame.classList.remove("is-ready");
      // A stale ready message can arrive while navigation has only an empty
      // document. Do not cache it and prevent the real load from wiring later.
      if (!doc || !win || !shellOf(doc)) return Promise.resolve(false);
      tab.reloadingDocument = null;
      const generation = (tab.wireGeneration || 0) + 1;
      tab.wireGeneration = generation; tab.wiredDocument = doc;
      const current = () => docs.includes(tab) && tab.wireGeneration === generation && docOf(tab) === doc;
      tab.wiring = wireDoc(tab, doc, win, current).catch(() => {
        if (!current()) return false;
        setStatus(tab, "error");
        if (tab.freshBoot) { tab.freshBoot = false; bootingFresh = Math.max(0, bootingFresh - 1); }
      });
      return tab.wiring;
    }
    // The child announces that its shell is ready before nested previews and
    // background history requests finish. Only our own held documents can do so.
    window.addEventListener("message", event => {
      if (event.origin !== location.origin || !event.data || event.data.type !== "thomas:surface-ready") return;
      const tab = docs.find(t => winOf(t) === event.source);
      if (tab) void prepareDoc(tab);
    });
    // "Open in its own tab" on a conversation row's menu (sidebar_history.js), from any document.
    window.addEventListener("thomas:conversation:open-tab", e => {
      const d = e.detail || {}; if (d.chatId) open({ mode: d.mode || "chat", chatId: String(d.chatId), title: d.title || "" });
    });
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
      frame.addEventListener("load", () => { void prepareDoc(tab); });
      frame.src = policy.docUrlFor({ mode, chatId: spec.chatId });
      rowWrap.appendChild(frame);
      // The frame is hidden until its page is up, and what showed through meanwhile was the home page's own old
      // content (a title and an empty body, no composer). A plain loading screen stands in until it is ready.
      const loader = document.createElement("div");
      loader.className = "bt-doc-loading";
      loader.setAttribute("aria-hidden", "true");
      loader.innerHTML = '<div class="bt-doc-loading-col"><i></i><i></i><i></i><span>Opening…</span></div><div class="bt-doc-loading-composer"></div>';
      rowWrap.appendChild(loader);
      tab.loader = loader;
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
    // Which mode the document on show is in, on the outer shell: a Build tab
    // wears Build's Dark look, and so does the chrome around it (tokens.css).
    function markActiveMode(mode) {
      const shell = document.getElementById("tc-shell");
      if (!shell) return;
      if (mode) shell.dataset.btActiveMode = mode; else delete shell.dataset.btActiveMode;
    }
    function hideAll() {
      docs.forEach(t => {
        t.frame.classList.remove("is-active"); t.frame.inert = true; t.frame.setAttribute("aria-hidden", "true");
        if (t.loader) t.loader.classList.remove("is-active");
        pauseWorld(t, true);
      });
      asideEl.inert = true;
      markActiveMode("");
    }
    function show(tab) {
      markActiveMode(tab.mode);
      tab.frame.classList.add("is-active"); tab.frame.inert = false; tab.frame.removeAttribute("aria-hidden");
      if (tab.loader) tab.loader.classList.add("is-active");
      pauseWorld(tab, false);
      tab.activatedAt = Date.now();
      const doc = docOf(tab);
      if (tab.ready && doc && (!doc.activeElement || doc.activeElement === doc.body)) {
        const input = doc.getElementById("tc-input");
        if (input) setTimeout(() => {
          // A switch, reload or intervening click owns focus after this was queued.
          if (getActiveId() === tab.id && tab.ready && docOf(tab) === doc && input.isConnected
            && (!doc.activeElement || doc.activeElement === doc.body)) input.focus();
        }, 40);
      }
    }
    function remove(tab) {
      const i = docs.indexOf(tab); if (i >= 0) docs.splice(i, 1);
      if (tab.freshBoot) { tab.freshBoot = false; bootingFresh = Math.max(0, bootingFresh - 1); }
      if (tab.loader) { tab.loader.remove(); tab.loader = null; }
      if (tab.frame) tab.frame.remove();
    }
    function reload(tab) {
      tab.reloadingDocument = docOf(tab);
      tab.wireGeneration = (tab.wireGeneration || 0) + 1; tab.wiredDocument = null;
      tab.ready = false; tab.wiring = null; tab.frame.classList.remove("is-ready"); setStatus(tab, "working");
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
