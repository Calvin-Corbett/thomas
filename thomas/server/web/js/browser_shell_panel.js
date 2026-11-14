/* browser_shell_panel.js — the side panel.
 *
 * It answers "what is on this tab": duplicate and reload for workspaces,
 * bookmark and escape hatch for websites, reload for a Thomas document. (The
 * Ask Thomas quick chat that shared this panel left with the titlebar pill
 * that opened it, in the 2026-10 Build redesign.)
 *
 * Split out of browser_shell.js, which had grown past the monolith guard's
 * 800-line soft limit. The panel owns its own DOM and open/closed state; the
 * shell hands it a context object and asks it for width when laying out
 * native web views. Behaviour is unchanged by the move.
 */
"use strict";

(function () {
  function create(ctx) {
    const { desktop, bodyRow, esc, h, SVG, byId, getActiveId,
      openWorkspaceTab, setStatus, navrow, onBoundsChange } = ctx;

    const sidePanel = h('<aside id="bt-sidepanel" aria-label="Side panel">'
      + '<div class="bt-sp-head"><b>Side panel</b><span id="bt-sp-ctx"></span>'
      + '<button id="bt-sp-close" type="button" title="Close side panel">' + SVG.x + "</button></div>"
      + '<div id="bt-sp-body"></div></aside>');
    bodyRow.appendChild(sidePanel);
    const spBody = sidePanel.querySelector("#bt-sp-body");
    const spCtx = sidePanel.querySelector("#bt-sp-ctx");
    const spTitle = sidePanel.querySelector(".bt-sp-head b");
    let panelOpen = false;
    let panelBtn = null;                       // set by the shell via attach()

    function bounds() { if (onBoundsChange) onBoundsChange(); }

    /* ── Context mode ─────────────────────────────────────────────────── */
    function renderContextPanel() {
      const t = byId(getActiveId()); if (!t) return;
      spTitle.textContent = "Side panel";
      spCtx.textContent = t.url || "";
      let html;
      if (t.kind === "ws") {
        html = '<div class="bt-pm-label">' + esc(t.title) + "</div>"
          + '<button class="bt-pm-item" type="button" data-sp="dup">' + SVG.plus + " Duplicate — fresh instance</button>"
          + '<button class="bt-pm-item" type="button" data-sp="reload">' + SVG.reload + " Reload this tab</button>"
          + '<p class="bt-sp-note">Each tab is its own live workspace — a duplicate starts clean while this one keeps its state.</p>';
      } else if (t.kind === "web") {
        html = '<div class="bt-pm-label">' + esc(t.title) + "</div>"
          + '<button class="bt-pm-item" type="button" data-sp="ext">' + SVG.ext + " Open in system browser</button>"
          + '<button class="bt-pm-item" type="button" data-sp="bm">' + SVG.plus + " Bookmark this page</button>";
      } else if (t.kind === "doc") {
        html = '<div class="bt-pm-label">' + esc(t.title) + "</div>"
          + '<button class="bt-pm-item" type="button" data-sp="reload">' + SVG.reload + " Reload this tab</button>"
          + '<p class="bt-sp-note">' + ({ chat: "This conversation", code: "This build", work: "This job" }[t.mode] || "This tab")
          + " has its own page. Switching tabs hides it and never resets it.</p>";
      } else {
        html = '<div class="bt-pm-label">' + esc(t.title) + "</div>"
          + '<p class="bt-sp-note">Whatever matters on the tab you’re on shows up here. On workspace tabs: duplicate and reload. On web tabs: bookmarks and escape hatches.</p>';
      }
      spBody.innerHTML = html;
      const dup = spBody.querySelector('[data-sp="dup"]');
      if (dup) dup.addEventListener("click", () => openWorkspaceTab(t.mode, true));
      const rel = spBody.querySelector('[data-sp="reload"]');
      if (rel) rel.addEventListener("click", () => {
        setStatus(t, "working");
        if (t.desktop && t.viewId != null && desktop) desktop.reload(t.viewId);
        else if (t.kind === "doc") navrow.querySelector("#bt-reload").click();
        else if (t.frame) t.frame.src = t.frame.src;
      });
      const ext = spBody.querySelector('[data-sp="ext"]');
      if (ext) ext.addEventListener("click", () => { try { window.open(t.url, "_blank", "noopener"); } catch (_) { } });
      const bm = spBody.querySelector('[data-sp="bm"]');
      if (bm) bm.addEventListener("click", () => navrow.querySelector("#bt-star").click());
    }

    /* ── Open / close / sync ──────────────────────────────────────────── */
    function sync() {
      if (panelOpen) renderContextPanel();
    }
    function close() {
      panelOpen = false;
      sidePanel.classList.remove("open");
      if (panelBtn) panelBtn.classList.remove("on");
      bounds();
    }
    // The panel button opens and closes it.
    function toggle() {
      if (!panelOpen) {
        panelOpen = true;
        sidePanel.classList.add("open");
        if (panelBtn) panelBtn.classList.add("on");
        renderContextPanel();
        bounds();
      } else close();
    }
    function attach(button) {
      panelBtn = button;
      button.addEventListener("click", toggle);
    }
    sidePanel.querySelector("#bt-sp-close").addEventListener("click", close);

    return {
      attach,
      sync,
      close,
      toggle,
      isOpen: () => panelOpen,
      width: () => (panelOpen ? sidePanel.getBoundingClientRect().width : 0),
      element: sidePanel,
    };
  }

  window.ThomasBrowserPanel = { create };
}());
