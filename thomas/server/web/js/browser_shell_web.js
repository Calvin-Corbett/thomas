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
      setTitle, setStatus, toast, viewTabs, reportBounds, getActiveId, openWorkspaceTab, omni,
      websearch, keys } = ctx;

    /* ── Web tabs: the internet, inside Thomas ──────────────────────────── */
    function hostOf(url) { try { return new URL(url).hostname; } catch (_) { return url; } }

    function attachWebFrame(tab, url) {
      if (desktop) {
        tab.desktop = true;
        setStatus(tab, "working");
        (async () => {
          try {
            tab.viewId = await desktop.createTab();
            viewTabs.set(tab.viewId, tab);
            await desktop.navigate(tab.viewId, url);
            if (getActiveId() === tab.id) { desktop.activateTab(tab.viewId); reportBounds(); }
          } catch (e) { setStatus(tab, "error"); toast("Couldn’t open " + url + ": " + (e && e.message || e)); }
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
    function openWebTab(url) {
      const tab = makeTab({ kind: "web", title: hostOf(url), url });
      attachWebFrame(tab, url);
      activate(tab.id);
      return tab;
    }
    function navigateWebTab(tab, url) {
      tab.url = url;
      setTitle(tab, hostOf(url));
      setStatus(tab, "working");
      if (tab.desktop) {
        if (tab.viewId != null) desktop.navigate(tab.viewId, url).catch(e => { setStatus(tab, "error"); toast(String(e && e.message || e)); });
      } else tab.frame.src = url;
      if (tab.id === getActiveId()) omni.value = url;
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
    function convertNtpToWeb(tab, url) {
      if (websearch().isSearchUrl(url)) return void websearch().show(tab, url);
      tab.page.remove(); tab.page = null;
      tab.kind = "web"; tab.url = url;
      tab.el.querySelector(".bt-tab-ic").innerHTML = SVG.globe;
      setTitle(tab, hostOf(url));
      attachWebFrame(tab, url);
      activate(tab.id);
    }

    /* ── History (desktop): recorded by main, browsed as one of our pages ── */
    async function renderHistoryPage(tab) {
      const rows = desktop ? await desktop.getHistory("", 200) : [];
      tab.page.innerHTML = '<div class="bt-inner" style="max-width: 760px;">'
        + '<div class="bt-pm-label">History — newest first</div>'
        + (rows.length
          ? rows.map(r => '<button class="bt-pm-item" type="button" data-hurl="' + esc(r.url) + '" style="gap: 12px;">'
            + '<span style="flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">' + esc(r.title || r.url) + "</span>"
            + '<span style="flex: 0 1 auto; color: var(--c-muted); font-size: 10px; font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 40%;">' + esc(r.url) + "</span></button>").join("")
          : '<p class="bt-sp-note">Nothing here yet — browse something and it lands in runtime/browser_profile/history.jsonl.</p>')
        + "</div>";
      tab.page.querySelectorAll("[data-hurl]").forEach(el => el.addEventListener("click", () => openWebTab(el.dataset.hurl)));
    }
    function openHistoryTab() {
      let tab = tabs.find(t => t.kind === "history");
      if (!tab) {
        tab = makeTab({ kind: "history", title: "History", url: "thomas://history" });
        tab.page = h('<div class="bt-page"></div>');
        bodyRow.appendChild(tab.page);
      }
      renderHistoryPage(tab);
      activate(tab.id);
    }

    return { hostOf, attachWebFrame, openWebTab, navigateWebTab, openUrl, openNtp, convertNtpToWeb, openHistoryTab };
  }

  window.ThomasBrowserWeb = { wire };
}());
