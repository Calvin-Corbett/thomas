/* browser_shell_search.js — search results as a Thomas page.
 *
 * Typing a question in the omnibox used to hand you off to duckduckgo.com.
 * That is a browser pointing at a search engine; this is a browser that has
 * one. The rows come from /api/search/web (the web.search tool) and the page
 * is rendered here, on our own origin — so none of this depends on whether
 * some other site is willing to be framed.
 *
 * The Thomas answer sits above the results the way an overview does, and it
 * is layered on afterwards: the links render the moment they arrive and never
 * wait on the model.
 *
 * SECURITY: every field below is attacker-controlled — whoever ranks third
 * for a query chooses the text in that row. Result text reaches the model
 * only as `page_context`, which the server fences as untrusted data
 * (routes/chat_page_context.py); it is never concatenated into the prompt
 * here. In the DOM it is escaped, and a row's href is only ever the url that
 * row carried.
 */
(function () {
  "use strict";

  const PREFIX = "thomas://search?q=";
  const TEXT_EVENTS = ["text", "agent_text", "delta", "assistant_delta", "message_delta"];

  function looksLikeUrl(q) { return /^(https?:\/\/|[\w-]+(\.[\w-]+)+([/?#]|$))/i.test(String(q || "").trim()); }
  function isSearchUrl(u) { return String(u || "").indexOf(PREFIX) === 0; }
  function queryOf(u) { try { return decodeURIComponent(String(u).slice(PREFIX.length)); } catch (_) { return ""; } }
  function toUrl(q) {
    const s = String(q || "").trim();
    if (looksLikeUrl(s)) return s.indexOf("http") === 0 ? s : "https://" + s;
    return PREFIX + encodeURIComponent(s);
  }

  const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ESCAPES[c]); }

  /* Escaping stops a row's text from breaking out of the attribute it sits
   * in, but it says nothing about the *scheme*: `javascript:...` survives
   * escaping intact and would run in the chrome page, which holds the desktop
   * bridge. A search result that is not a web address is not a result. */
  function webUrl(u) {
    try {
      const p = new URL(String(u || ""));
      return (p.protocol === "http:" || p.protocol === "https:") ? p.href : "";
    } catch (_) { return ""; }
  }

  // A search result shows where it goes before you click it.
  function crumb(url) {
    try {
      const u = new URL(url);
      const parts = u.pathname.split("/").filter(Boolean).slice(0, 3);
      return u.hostname.replace(/^www\./, "") + (parts.length ? " › " + parts.join(" › ") : "");
    } catch (_) { return String(url || ""); }
  }

  function chunkOf(evt) {
    const c = evt.text != null ? evt.text : (evt.delta != null ? evt.delta : evt.content);
    return typeof c === "string" ? c : "";
  }

  function rowHTML(r, i) {
    return '<article class="bt-sr" data-i="' + i + '">'
      + '<div class="bt-sr-crumb">' + esc(crumb(r.url)) + "</div>"
      + '<a class="bt-sr-title" href="' + esc(r.url) + '">' + esc(r.title || crumb(r.url)) + "</a>"
      + (r.snippet ? '<p class="bt-sr-snip">' + esc(r.snippet) + "</p>" : "")
      + "</article>";
  }

  /* Asked for only once the links are on screen, and it says when it has no
   * answer rather than leaving an empty card sitting there. */
  async function askThomas(card, query, rows) {
    const consumer = window.ThomasChatStreamConsumer;
    if (!consumer) { card.remove(); return; }
    const body = card.querySelector(".bt-ai-body");
    const context = rows.slice(0, 6).map((r, i) =>
      (i + 1) + ". " + (r.title || "") + "\n" + (r.url || "") + "\n" + (r.snippet || "")).join("\n\n");
    try {
      const res = await fetch("/api/v2/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: "A web search for: " + query
            + "\n\nAnswer it in two to four sentences using the search results in the browser"
            + " context. If they do not actually answer it, say so instead of guessing.",
          surface_mode: "chat",
          // An overview is not a conversation: it must not land in the sidebar.
          temporary: true,
          page_context: {
            title: query + " — search results",
            url: PREFIX + encodeURIComponent(query),
            text: context,
          },
        }),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      let acc = "";
      await consumer.consume(res, evt => {
        if (TEXT_EVENTS.indexOf(evt.type) < 0) return;
        const c = chunkOf(evt);
        if (!c) return;
        acc += c;
        card.classList.remove("is-loading");
        body.textContent = acc;
      });
      if (!acc.trim()) throw new Error("no answer came back");
    } catch (e) {
      card.classList.remove("is-loading");
      card.classList.add("is-quiet");
      body.textContent = "Thomas couldn't answer this one — " + (e && e.message || e);
    }
  }

  async function fill(page, query, openUrl, done) {
    const results = page.querySelector(".bt-sr-list");
    const card = page.querySelector(".bt-ai");
    let rows = [];
    try {
      const res = await fetch("/api/search/web?count=10&q=" + encodeURIComponent(query), { cache: "no-store" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.error || "HTTP " + res.status);
      rows = (Array.isArray(data.results) ? data.results : [])
        .map(r => ({ title: r.title, snippet: r.snippet, url: webUrl(r.url) }))
        .filter(r => r.url);
    } catch (e) {
      card.remove();
      results.innerHTML = '<p class="bt-sr-empty">Search failed — ' + esc(String(e && e.message || e)) + "</p>";
      results.removeAttribute("aria-busy");
      done(false);
      return;
    }
    results.removeAttribute("aria-busy");
    if (!rows.length) {
      card.remove();
      results.innerHTML = '<p class="bt-sr-empty">No results for ' + esc(query) + ".</p>";
      done(true);
      return;
    }
    results.innerHTML = rows.map(rowHTML).join("");
    results.querySelectorAll(".bt-sr-title").forEach(a => a.addEventListener("click", e => {
      // A plain click navigates here, the way a search result does; the
      // modifier conventions belong to the browser above us.
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      openUrl(a.getAttribute("href"));
    }));
    done(true);
    askThomas(card, query, rows);
  }

  function pageHTML(query) {
    return '<div class="bt-sr-page">'
      + '<div class="bt-sr-head"><span class="bt-sr-mark" aria-hidden="true"></span>'
      + '<h1 class="bt-sr-q">' + esc(query) + "</h1></div>"
      + '<section class="bt-ai is-loading" aria-live="polite">'
      + '<div class="bt-ai-label">Thomas</div><div class="bt-ai-body"></div></section>'
      + '<div class="bt-sr-list" aria-busy="true"><p class="bt-sr-empty">Searching…</p></div></div>';
  }

  function wire(ctx) {
    /* A tab becoming the results page gives up whatever it was showing --
     * a leftover frame or native view paints straight over the results,
     * which reads as a broken search rather than a stale view. */
    function detach(tab) {
      if (tab.frame && !tab.adopted) { tab.frame.remove(); tab.frame = null; }
      if (tab.fallback) { tab.fallback.remove(); tab.fallback = null; }
      if (tab.viewId != null && ctx.desktop) {
        ctx.desktop.closeTab(tab.viewId);
        ctx.viewTabs.delete(tab.viewId);
        tab.viewId = null;
        tab.desktop = false;
      }
    }

    function show(tab, url) {
      const query = queryOf(url);
      detach(tab);
      tab.kind = "search";
      tab.url = url;
      if (!tab.page) { tab.page = ctx.h('<div class="bt-page"></div>'); ctx.body.appendChild(tab.page); }
      tab.page.innerHTML = pageHTML(query);
      const ic = tab.el.querySelector(".bt-tab-ic");
      if (ic) ic.innerHTML = ctx.icon;
      ctx.setTitle(tab, query);
      ctx.setStatus(tab, "working");
      ctx.activate(tab.id);
      fill(tab.page, query, ctx.openUrl, ok => ctx.setStatus(tab, ok ? "done" : "error"));
      return tab;
    }
    return { show, toUrl, looksLikeUrl, isSearchUrl, queryOf };
  }

  // rowHTML and webUrl are exported because they are the two places a bad
  // result can turn into an attack, and both are pure enough to pin
  // without a DOM (tests/web_node/browser_search_rows.mjs).
  window.ThomasBrowserSearch = { wire, toUrl, looksLikeUrl, isSearchUrl, queryOf, webUrl, rowHTML };
})();
