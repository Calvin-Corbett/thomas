/* browser_shell_panel.js — the side panel, and the Ask Thomas quick chat.
 *
 * One surface with two personalities:
 *  - CONTEXT mode answers "what is on this tab" — artifacts, duplicate and
 *    reload for workspaces, bookmark and escape hatch for websites.
 *  - CHAT mode is the quick chat: a small composer for the question that does
 *    not deserve a whole tab, wired to the REAL backend through
 *    ThomasWorkspaceChatTransport (POST /api/v2/chat), carrying the current
 *    tab as a structured page_context field. The server wraps that field as
 *    untrusted data (chat_page_context.py) — a page writes its own title.
 *
 * Split out of browser_shell.js, which had grown past the monolith guard's
 * 800-line soft limit. The panel owns its own DOM and open/closed state; the
 * shell hands it a context object and asks it for width when laying out
 * native web views. Behaviour is unchanged by the move.
 */
"use strict";

(function () {
  function create(ctx) {
    const { desktop, bodyRow, esc, h, SVG, byId, getActiveId, activate, homeTabId,
      openWorkspaceTab, setStatus, navrow, onBoundsChange } = ctx;

    const sidePanel = h('<aside id="bt-sidepanel" aria-label="Side panel">'
      + '<div class="bt-sp-head"><b>Side panel</b><span id="bt-sp-ctx"></span>'
      + '<button id="bt-sp-close" type="button" title="Close side panel">' + SVG.x + "</button></div>"
      + '<div id="bt-sp-body"></div></aside>');
    bodyRow.appendChild(sidePanel);
    const spBody = sidePanel.querySelector("#bt-sp-body");
    const spCtx = sidePanel.querySelector("#bt-sp-ctx");
    const spTitle = sidePanel.querySelector(".bt-sp-head b");
    let panelOpen = false, panelMode = "context";
    let panelBtn = null;                       // set by the shell via attach()

    function bounds() { if (onBoundsChange) onBoundsChange(); }

    /* ── Context mode ─────────────────────────────────────────────────── */
    function renderContextPanel() {
      const t = byId(getActiveId()); if (!t) return;
      sidePanel.classList.remove("chat-mode");
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
          + '<button class="bt-pm-item" type="button" data-sp="bm">' + SVG.plus + " Bookmark this page</button>"
          + '<p class="bt-sp-note">Ask Thomas about this page from the quick chat — he knows which tab you’re on.</p>';
      } else if (t.kind === "doc") {
        html = '<div class="bt-pm-label">' + esc(t.title) + "</div>"
          + '<button class="bt-pm-item" type="button" data-sp="reload">' + SVG.reload + " Reload this tab</button>"
          + '<p class="bt-sp-note">' + ({ chat: "This conversation", code: "This build", work: "This job" }[t.mode] || "This tab")
          + " has its own page. Switching tabs hides it and never resets it.</p>";
      } else {
        html = '<div class="bt-pm-label">' + esc(t.title) + "</div>"
          + '<p class="bt-sp-note">Whatever matters on the tab you’re on shows up here. On workspace tabs: duplicate and reload. On web tabs: bookmarks and escape hatches. “Ask Thomas” turns this panel into a quick chat.</p>';
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

    /* ── Quick chat: the real pipeline ────────────────────────────────── */
    const qc = { session: null, thread: [], turn: null };
    function qcCtxHTML() {
      const t = byId(getActiveId());
      return t ? SVG.eye + " Seeing <b>" + esc(t.title) + "</b> · " + esc(t.url || "") : "";
    }
    function qcPageContext() {
      // "He knows where you are", concretely: the current tab rides along as a
      // STRUCTURED field. The server wraps it as untrusted data, because page
      // titles are written by strangers.
      const t = byId(getActiveId());
      if (!t) return undefined;
      return { title: String(t.title || ""), url: String(t.url || "") };
    }
    function qcMsgsHTML() {
      if (!qc.thread.length) return '<p class="bt-sp-note">Ask the small stuff here — it goes to the real Thomas, and your page stays put behind this panel.</p>';
      return qc.thread.map(m => m.role === "u"
        ? '<div class="bt-qc-u">' + esc(m.text) + "</div>"
        : '<div class="bt-qc-t' + (m.error ? " bt-qc-err" : "") + '"><span class="bt-appmark" style="margin:0; flex:0 0 auto;"><span></span><span></span></span><span>' + (m.pending ? '<span class="bt-qc-dots"><span></span><span></span><span></span></span>' : esc(m.text)) + "</span></div>").join("");
    }
    function renderQuickChat() {
      spTitle.textContent = "Ask Thomas";
      spCtx.textContent = "quick chat · knows where you are";
      sidePanel.classList.add("chat-mode");
      spBody.innerHTML = '<div class="bt-qc-ctx" id="bt-qc-ctx">' + qcCtxHTML() + "</div>"
        + '<div class="bt-qc-msgs" id="bt-qc-msgs">' + qcMsgsHTML() + "</div>"
        + '<div class="bt-qc-status" id="bt-qc-status"></div>'
        + '<button class="bt-pm-item" id="bt-qc-promote" type="button">' + SVG.spark + " Continue in the full chat</button>"
        + '<div class="bt-qc-composer">'
        + '<textarea id="bt-qc-input" rows="1" placeholder="Quick question…" aria-label="Quick question"></textarea>'
        + '<button id="bt-qc-send" type="button" title="Send">' + SVG.up + "</button></div>";
      const msgs = spBody.querySelector("#bt-qc-msgs");
      const statusEl = spBody.querySelector("#bt-qc-status");
      const inp = spBody.querySelector("#bt-qc-input");
      msgs.scrollTop = msgs.scrollHeight;

      function paint() {
        msgs.innerHTML = qcMsgsHTML();
        msgs.scrollTop = msgs.scrollHeight;
      }
      function sendQuick() {
        const text = inp.value.trim();
        if (!text || qc.turn) return;
        if (!window.ThomasWorkspaceChatTransport) {
          qc.thread.push({ role: "t", text: "The chat transport isn’t loaded — reload the page and try again.", error: true });
          paint(); return;
        }
        inp.value = "";
        qc.thread.push({ role: "u", text });
        const reply = { role: "t", text: "", pending: true };
        qc.thread.push(reply);
        paint();
        qc.turn = window.ThomasWorkspaceChatTransport.beginTurn(
          {
            message: text,
            page_context: qcPageContext(),
            session_id: qc.session || undefined,
            surface_mode: "chat",
          },
          {
            onSession: id => { qc.session = id; },
            onStatus: s => { statusEl.textContent = s || ""; },
            onAnswer: full => { reply.text = full; reply.pending = false; paint(); },
          }
        );
        qc.turn.promise
          .then(finalText => { reply.text = finalText || reply.text || "(no answer)"; reply.pending = false; })
          .catch(err => { reply.text = "That didn’t go through: " + (err && err.message ? err.message : err); reply.error = true; reply.pending = false; })
          .finally(() => { qc.turn = null; statusEl.textContent = ""; paint(); });
      }
      spBody.querySelector("#bt-qc-send").addEventListener("click", sendQuick);
      inp.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuick(); } });
      spBody.querySelector("#bt-qc-promote").addEventListener("click", async () => {
        activate(homeTabId());
        // The quick chat talks to the same /api/v2/chat namespace as the
        // composer, so its session is a real conversation and should be
        // OPENED, not retyped. The sidebar row for it is the shell's own way
        // in; wait briefly for the history to catch up before giving up.
        // If the sidebar already lists this conversation, OPEN it -- the quick
        // chat writes to the same /api/v2/chat namespace as the composer, so
        // it is a real conversation, not a scratch buffer.
        //
        // It usually will not be listed: the shell fetches its history once
        // and re-renders from that cached list, so a session created since
        // then has no row, and there is no exposed way to make it refetch.
        // Fixing that properly means touching chat.html, which currently
        // cannot be committed (2998 lines against a 1000-line hard limit).
        // Until then the question is carried across rather than lost.
        if (qc.session) {
          const escaped = window.CSS && CSS.escape ? CSS.escape(qc.session) : qc.session;
          const row = document.querySelector('#tc-chats [data-history-id="' + escaped + '"]');
          if (row) { row.click(); return; }
        }
        // It never showed up (a brand-new session may not be listed yet), so
        // carry the question across rather than losing it.
        const lastQ = [...qc.thread].reverse().find(m => m.role === "u");
        const input = document.getElementById("tc-input");
        if (input) {
          input.value = lastQ ? "Continuing from the quick chat: " + lastQ.text : "";
          input.dispatchEvent(new Event("input", { bubbles: true }));
          input.focus();
        }
      });
      inp.focus();
    }

    /* ── Open / close / sync ──────────────────────────────────────────── */
    function openQuickChat() {
      panelOpen = true; panelMode = "chat";
      sidePanel.classList.add("open");
      if (panelBtn) panelBtn.classList.add("on");
      renderQuickChat();
      bounds();
    }
    function sync() {
      if (!panelOpen) return;
      if (panelMode === "context") renderContextPanel();
      else {
        const chip = spBody.querySelector("#bt-qc-ctx");
        if (chip) chip.innerHTML = qcCtxHTML();
      }
    }
    function close() {
      panelOpen = false;
      sidePanel.classList.remove("open", "chat-mode");
      if (panelBtn) panelBtn.classList.remove("on");
      bounds();
    }
    // The panel button cycles: closed -> context -> (chat -> context) -> closed.
    function toggle() {
      if (!panelOpen) {
        panelOpen = true; panelMode = "context";
        sidePanel.classList.add("open");
        if (panelBtn) panelBtn.classList.add("on");
        renderContextPanel();
        bounds();
      } else if (panelMode === "chat") {
        panelMode = "context";
        renderContextPanel();
      } else close();
    }
    function attach(button) {
      panelBtn = button;
      button.addEventListener("click", toggle);
    }
    sidePanel.querySelector("#bt-sp-close").addEventListener("click", close);

    return {
      attach,
      openQuickChat,
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
