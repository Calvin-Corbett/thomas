/* browser_shell_web.js — web tabs, the + page and the History page.
 *
 * Moved verbatim out of browser_shell.js, which sat at 794 lines against the
 * monolith guard's 800-line soft limit, so the next feature had nowhere to
 * land. Behaviour is unchanged by the move: the shell hands this module a
 * context object, the same seam browser_shell_search.js uses, and re-exports
 * the functions under their old names at their old position.
 *
 * `websearch` arrives as a getter because the search module is created after
 * this one; it is only dereferenced when a user acts.
 */
"use strict";

(function () {
  function wire(ctx) {
    const { desktop, bodyRow, h, esc, SVG, icons, wsByMode, bookmarks, makeTab, byId, activate,
      setTitle, setStatus, toast, viewTabs, reportBounds, getActiveId, openWorkspaceTab, omni, getTabs,
      websearch, keys, syncNav } = ctx;

    /* ── Web tabs: the internet, inside Thomas ──────────────────────────── */
    function hostOf(url) { try { return new URL(url).hostname; } catch (_) { return url; } }

    function attachWebFrame(tab, url) {
      if (desktop) {
        tab.desktop = true;
        // A fresh view has a fresh history, and whatever the last one reported
        // says nothing about it. Undefined means "not reported yet", which is
        // the state where Back and Forward ask the view rather than assume.
        tab.canBack = tab.canFwd = undefined;
        const request = tab.webRequest = (tab.webRequest || 0) + 1;
        const stillCurrent = () => tab.webRequest === request && tab.kind === "web" && getTabs().includes(tab);
        setStatus(tab, "working");
        (async () => {
          let viewId = null;
          try {
            viewId = await desktop.createTab();
            if (!stillCurrent()) { await desktop.closeTab(viewId); return; }
            tab.viewId = viewId;
            viewTabs.set(viewId, tab);
            await desktop.navigate(viewId, tab.url);
            if (stillCurrent() && getActiveId() === tab.id) { desktop.activateTab(viewId); reportBounds(); }
          } catch (e) {
            if (!stillCurrent()) return;
            setStatus(tab, "error"); toast("Couldn’t open " + tab.url + ": " + (e && e.message || e));
          }
        })();
        return;
      }
      const frame = document.createElement("iframe");
      frame.className = "bt-frame bt-web-frame";
      frame.title = tab.title;
      frame.addEventListener("load", () => setStatus(tab, "done"));
      setStatus(tab, "working");
      frame.src = url;
      bodyRow.appendChild(frame);
      tab.frame = frame;
      // Sites that refuse framing render blank; the honest exit is one click.
      tab.fallback = h('<button class="bt-web-fallback" type="button" title="Some sites refuse to be embedded — this opens the same address in your system browser">' + SVG.ext + " Open externally</button>");
      tab.fallback.addEventListener("click", () => { try { window.open(tab.url, "_blank", "noopener"); } catch (_) { } });
      bodyRow.appendChild(tab.fallback);
    }
    /* A web tab that arrived from another window: its native view already
     * exists and holds the page, so this only gives it a tab here. */
    function adoptWebView(spec) {
      const tab = makeTab({ kind: "web", title: spec.title || hostOf(spec.url), url: spec.url });
      tab.desktop = true;
      tab.viewId = spec.viewId;
      tab.canBack = tab.canFwd = undefined;
      viewTabs.set(spec.viewId, tab);
      if (spec.favicon) { const slot = tab.el.querySelector(".bt-tab-ic"); const img = new Image(); img.width = img.height = 14; img.alt = ""; img.addEventListener("load", () => { slot.innerHTML = ""; slot.appendChild(img); }); img.src = spec.favicon; }
      setStatus(tab, "done");
      activate(tab.id);
      return tab;
    }
    function openWebTab(url) {
      const tab = makeTab({ kind: "web", title: hostOf(url), url });
      attachWebFrame(tab, url);
      activate(tab.id);
      return tab;
    }
    /* `step` says which button caused this navigation: nothing for a fresh
     * one, "back" for a step along the trail, "forward" for a step along the
     * way ahead. websearch.recordStep turns that into where the page being
     * left belongs, and it is the same function the results page uses, so a
     * tab's record reads the same however it got here.
     *
     * A desktop tab is a native destination: every navigation lands in the
     * same WebContentsView, whose own history already knows these pages and
     * is asked first.
     */
    function navigateWebTab(tab, url, step) {
      websearch().recordStep(tab, url, step, tab.desktop);
      tab.url = url;
      setTitle(tab, hostOf(url));
      setStatus(tab, "working");
      if (tab.desktop) {
        if (tab.viewId != null) desktop.navigate(tab.viewId, url).catch(e => { setStatus(tab, "error"); toast(String(e && e.message || e)); });
      } else tab.frame.src = url;
      // This is the one navigation that does not go through activate(), and it
      // has just changed the tab's record: typing an address ends the way
      // ahead, so Forward has to go dark with it rather than stay lit from the
      // page before. (A native view reports its own state a moment later.)
      if (tab.id === getActiveId()) { omni.value = url; syncNav(); }
    }
    const SEARCHABLE = { web: 1, ntp: 1, search: 1 };
    function openUrl(url) {
      const t = byId(getActiveId());
      if (websearch().isSearchUrl(url)) return void websearch().show(t && SEARCHABLE[t.kind] ? t : openNtp(), url);
      if (t && t.kind === "web") navigateWebTab(t, url);
      // Clicking a result navigates where you are, the way a search result
      // does; both page kinds hand their page over to the web frame.
      else if (t && (t.kind === "ntp" || t.kind === "search")) convertNtpToWeb(t, url);
      else openWebTab(url);
    }

    /* ── The + page: Thomas mark, search, favorites, workspace tiles ────── */
    // The honest shortcut table: only bindings a plain browser lets through.
    function keysHTML() {
      const table = keys && keys() ? keys().bindings().filter(b => b.everywhere) : [];
      if (!table.length) return "";
      return '<div class="bt-ntp-label">Shortcuts</div><div class="bt-ntp-keys">'
        + table.map(b => '<span class="bt-ntp-key"><kbd>' + esc(b.keys) + "</kbd>" + esc(b.does) + "</span>").join("")
        + "</div>";
    }
    function ntpHTML() {
      const bmTiles = bookmarks.slice(0, 8).map((bm, i) =>
        '<button class="bt-tile" type="button" data-bm="' + i + '"><span class="bt-tile-ic"><span class="bm" style="background:' + esc(bm.c || "#556") + ';">' + esc(bm.t || bm.label.slice(0, 1).toUpperCase()) + "</span></span><span>" + esc(bm.label) + "</span></button>").join("");
      const wsTiles = Object.keys(wsByMode).filter(m => m !== "settings").map(m =>
        '<button class="bt-tile" type="button" data-ws="' + esc(m) + '"><span class="bt-tile-ic">' + (icons().glyph(wsByMode[m].icon, 20) || SVG.globe) + "</span><span>" + esc(wsByMode[m].label) + "</span></button>").join("");
      return '<div class="bt-ntp">'
        + '<div class="bt-ntp-mark" aria-hidden="true"><span></span><span></span></div>'
        + '<div class="bt-ntp-name">Thomas</div>'
        + '<div class="bt-bigsearch">' + SVG.search + '<input placeholder="Search or type a URL — opens inside Thomas" aria-label="Search the web"></div>'
        + '<div class="bt-shortcuts">' + bmTiles + "</div>"
        + '<div class="bt-ntp-label">Workspaces — each tile opens a fresh tab</div>'
        + '<div class="bt-shortcuts">' + wsTiles + "</div>"
        + keysHTML() + "</div>";
    }
    function openNtp() {
      const tab = makeTab({ kind: "ntp", title: "New tab", url: "thomas://new-tab" });
      tab.page = h('<div class="bt-page"></div>');
      tab.page.innerHTML = ntpHTML();
      bodyRow.appendChild(tab.page);
      bindNtp(tab);
      activate(tab.id);
      return tab;
    }
    function bindNtp(tab) {
      const inp = tab.page.querySelector(".bt-bigsearch input");
      inp.addEventListener("keydown", e => {
        if (e.key === "Enter" && inp.value.trim()) convertNtpToWeb(tab, websearch().toUrl(inp.value));
      });
      tab.page.querySelectorAll("[data-bm]").forEach(el => el.addEventListener("click", () => {
        const bm = bookmarks[Number(el.dataset.bm)];
        if (bm) convertNtpToWeb(tab, bm.url);
      }));
      tab.page.querySelectorAll("[data-ws]").forEach(el => el.addEventListener("click", () => {
        openWorkspaceTab(el.dataset.ws, true);
      }));
    }
    function convertNtpToWeb(tab, url, step) {
      if (websearch().isSearchUrl(url)) return void websearch().show(tab, url, step);
      if (tab.searchController) tab.searchController.abort();
      // A result opens in a frame holding a single entry, or in a view made
      // moments ago: in the desktop app the results page it came from is the
      // one hop neither history knows, so the tab is told to owe it. Stepping
      // BACK to a page means those results are ahead, not behind -- owing them
      // both ways is how a Back button starts bouncing between two pages.
      tab.searchOrigin = step !== "back" && desktop && tab.kind === "search" ? tab.url : null;
      websearch().recordStep(tab, url, step, !!desktop);
      if (tab.page) { tab.page.remove(); tab.page = null; }
      tab.kind = "web"; tab.url = url;
      tab.el.querySelector(".bt-tab-ic").innerHTML = SVG.globe;
      setTitle(tab, hostOf(url));
      attachWebFrame(tab, url);
      activate(tab.id);
    }

    /* ── History (desktop): recorded by main, browsed as one of our pages ── */
    async function renderHistoryPage(tab, request) {
      const rows = desktop ? await desktop.getHistory("", 200) : [];
      if (tab.historyRequest !== request || !getTabs().includes(tab)) return;
      tab.page.innerHTML = '<div class="bt-inner" style="max-width: 760px;">'
        + '<div class="bt-pm-label">History — newest first</div>'
        + (rows.length
          ? rows.map(r => '<button class="bt-pm-item" type="button" data-hurl="' + esc(r.url) + '" style="gap: 12px;">'
            + '<span style="flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">' + esc(r.title || r.url) + "</span>"
            + '<span style="flex: 0 1 auto; color: var(--c-muted); font-size: 10px; font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 40%;">' + esc(r.url) + "</span></button>").join("")
          : '<p class="bt-sp-note">Pages you visit will appear here.</p>')
        + "</div>";
      tab.page.querySelectorAll("[data-hurl]").forEach(el => el.addEventListener("click", () => openWebTab(el.dataset.hurl)));
      setStatus(tab, "done");
    }
    function openHistoryTab() {
      let tab = getTabs().find(t => t.kind === "history");
      if (!tab) {
        tab = makeTab({ kind: "history", title: "History", url: "thomas://history" });
        tab.page = h('<div class="bt-page"></div>');
        bodyRow.appendChild(tab.page);
      }
      const request = tab.historyRequest = (tab.historyRequest || 0) + 1;
      tab.page.textContent = "Loading history…";
      setStatus(tab, "working");
      renderHistoryPage(tab, request).catch(error => {
        if (tab.historyRequest !== request || !getTabs().includes(tab)) return;
        tab.page.textContent = "History could not be loaded. Open History again to retry.";
        setStatus(tab, "error");
        console.error("History could not be loaded", error);
      });
      activate(tab.id);
    }

    return { hostOf, attachWebFrame, adoptWebView, openWebTab, navigateWebTab, openUrl, openNtp, convertNtpToWeb, openHistoryTab };
  }

  window.ThomasBrowserWeb = { wire };
}());
