/* browser_shell_desktop.js — everything that only matters inside the app.
 *
 * The browser chrome runs in two places: the Electron desktop app, where web
 * tabs are real WebContentsViews, and a plain browser, where they are iframes
 * and most of the web refuses to be framed. This module holds the half that
 * only exists in the first case, so browser_shell.js stays readable as the
 * surface both share.
 *
 * Three jobs:
 *  - NATIVE MENUS. A WebContentsView paints over the chrome page, so an HTML
 *    dropdown is invisible whenever a web tab is active. The profile menu
 *    becomes a real OS menu; theme picking still drives the shell's own
 *    switcher rather than reimplementing it.
 *  - TAB EVENTS. Titles, URLs, load state, crashes and downloads arrive from
 *    the main process and land on the matching tab.
 *  - GEOMETRY AND RESTORE. Native views are positioned by the main process,
 *    so the page reports its content rect whenever it changes, and reopens
 *    the tabs the last session left behind.
 */
"use strict";

(function () {
  function wire(ctx) {
    const { desktop, bodyRow, profBtn, omni, viewTabs, toast, setTitle, setStatus,
      setFavicon, openWebTab, openWorkspaceTab, openHistoryTab, activate,
      homeTabId, getActiveId, reportBounds } = ctx;
    if (!desktop) return { nativeMenus: false };

    /* ── Native profile menu ──────────────────────────────────────────── */
    function currentThemeKey() {
      return (window.ThomasWorkspaceShell && window.ThomasWorkspaceShell.storedTheme()) || "nebula";
    }
    function pickTheme(key) {
      // Drive the shell's OWN theme switcher: it applies the tokens, retints
      // the mascot, rewrites the welcome copy and persists the choice.
      // Opening the menu is what renders the options in the first place.
      const themes = window.ThomasChatThemes && window.ThomasChatThemes.THEMES;
      const name = themes && themes[key] ? themes[key].name : "";
      const btn = document.getElementById("tc-theme-btn");
      const options = document.getElementById("tc-theme-options");
      if (!btn || !options || !name) return;
      btn.click();
      const option = [...options.children].find(b => (b.textContent || "").trim().startsWith(name));
      if (option) option.click();
      else btn.click();                      // nothing matched: close it again
    }
    async function openProfileMenu() {
      const themes = (window.ThomasChatThemes && window.ThomasChatThemes.THEMES) || {};
      const active = currentThemeKey();
      const items = [
        { id: "settings", label: "Settings" },
        { id: "history", label: "History" },
        { type: "separator" },
        ...Object.keys(themes).map(key => ({
          id: "theme:" + key, label: themes[key].name, checked: key === active,
        })),
        { type: "separator" },
        { id: "redesign", label: "Redesign with AI" },
      ];
      const rect = profBtn.getBoundingClientRect();
      let chosen;
      try {
        chosen = await desktop.popupMenu(items, rect.left, rect.bottom + 2);
      } catch (_) {
        chosen = "__unsupported__";
      }
      if (chosen === "__unsupported__") return false;   // caller shows the HTML menu
      if (!chosen) return true;                          // dismissed
      if (chosen === "settings") openWorkspaceTab("settings");
      else if (chosen === "history") openHistoryTab();
      else if (chosen === "redesign") { const b = document.getElementById("tc-redesign-btn"); if (b) b.click(); }
      else if (chosen.startsWith("theme:")) pickTheme(chosen.slice(6));
      return true;
    }

    /* ── Tab events from the main process ─────────────────────────────── */
    desktop.onTabEvent(evt => {
      if (evt.type === "new-window") { if (evt.value) openWebTab(evt.value); return; }
      if (evt.type === "download") {
        const d = evt.value || {};
        if (d.state === "completed") toast("Downloaded " + d.filename + " → Downloads");
        else if (d.state === "interrupted" || d.state === "cancelled") toast("Download " + d.state + ": " + d.filename);
        return;
      }
      const tab = viewTabs.get(evt.id);
      if (!tab) return;
      if (evt.type === "favicon" && evt.value) setFavicon(tab, evt.value);
      else if (evt.type === "title" && evt.value && evt.value !== tab.title) setTitle(tab, evt.value);
      else if (evt.type === "url" && evt.value) { tab.url = evt.value; if (tab.id === getActiveId()) omni.value = evt.value; }
      else if (evt.type === "loading") setStatus(tab, evt.value ? "working" : "done");
      else if (evt.type === "crashed") { setStatus(tab, "error"); toast("That tab’s renderer crashed (" + evt.value + ") — reload it."); }
    });

    /* ── Dropdowns the shell already owns ─────────────────────────────── */
    // The model picker, Tools, the project library and the theme list are all
    // HTML popups that live in the chrome page. A native web view paints over
    // that page, so while a web tab is showing they open behind it and read
    // as dead controls. Rather than rebuild each one natively -- the model
    // picker is a lazily-rendered accordion -- the view steps aside for
    // exactly as long as a popup is open.
    const OVERLAYS = ["#tc-model-menu", "#tc-theme-menu", "#tc-tools-menu", "#tc-code-library-menu"];
    let viewSuspended = false;
    function anyOverlayOpen() {
      return OVERLAYS.some(sel => {
        const el = document.querySelector(sel);
        return el && getComputedStyle(el).display !== "none";
      });
    }
    let overlayWatchdog = 0;
    function syncOverlaySuspension() {
      const open = anyOverlayOpen();
      if (open === viewSuspended) return;
      viewSuspended = open;
      desktop.suspendView(open);
      // A view that hides and never comes back is worse than the bug this
      // fixes, so while it is hidden we keep asking whether it may return
      // rather than trusting one close event to arrive.
      clearInterval(overlayWatchdog);
      if (open) overlayWatchdog = setInterval(syncOverlaySuspension, 400);
    }
    OVERLAYS.forEach(sel => {
      const el = document.querySelector(sel);
      if (!el) return;
      new MutationObserver(syncOverlaySuspension).observe(el, {
        attributes: true, attributeFilter: ["style", "class"],
      });
    });
    // An outside click closes these without touching their style attribute in
    // every path, so re-check after any click lands.
    document.addEventListener("click", () => setTimeout(syncOverlaySuspension, 0), true);

    /* ── Geometry and session restore ─────────────────────────────────── */
    new ResizeObserver(() => reportBounds()).observe(bodyRow);
    window.addEventListener("resize", reportBounds);
    desktop.onRestore(urls => {
      urls.slice(0, 12).forEach(u => openWebTab(u));
      activate(homeTabId());
    });
    desktop.ready();

    return { nativeMenus: true, openProfileMenu };
  }

  window.ThomasBrowserDesktop = { wire };
}());
