/* browser_shell_search.js — search results as a Thomas page.
 *
 * Typing a question in the omnibox used to hand you off to duckduckgo.com.
 * That is a browser pointing at a search engine; this is a browser that has
 * one. The rows come from /api/search/web (the web.search tool) and the page
 * is rendered here, on our own origin — so none of this depends on whether
 * some other site is willing to be framed.
 *
 * The Thomas overview sits beside the results on wide screens and above them
 * on narrow screens. It is layered on afterwards: links render as soon as
 * they arrive and never wait on the model.
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
    if (looksLikeUrl(s)) return /^https?:\/\//i.test(s) ? s : "https://" + s;
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
      + '<div class="bt-sr-identity"><span class="bt-sr-avatar" aria-hidden="true">' + esc(crumb(r.url).charAt(0).toUpperCase()) + '</span>'
      + '<div class="bt-sr-crumb">' + esc(crumb(r.url)) + "</div></div>"
      + '<a class="bt-sr-title" href="' + esc(r.url) + '">' + esc(r.title || crumb(r.url)) + "</a>"
      + (r.snippet ? '<p class="bt-sr-snip">' + esc(r.snippet) + "</p>" : "")
      + "</article>";
  }

  /* Asked for only once the links are on screen, and it says when it has no
   * answer rather than leaving an empty card sitting there. */
  async function askThomas(card, query, rows, signal) {
    const consumer = window.ThomasChatStreamConsumer;
    if (!consumer) { card.remove(); return; }
    const body = card.querySelector(".bt-ai-body");
    const context = rows.slice(0, 6).map((r, i) =>
      (i + 1) + ". " + (r.title || "") + "\n" + (r.url || "") + "\n" + (r.snippet || "")).join("\n\n");
    try {
      const res = await fetch("/api/v2/chat", {
        method: "POST",
        signal,
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
      if (signal.aborted || !card.isConnected) return;
      if (!res.ok) throw new Error("HTTP " + res.status);
      let acc = "";
      await consumer.consume(res, evt => {
        if (signal.aborted || !card.isConnected || TEXT_EVENTS.indexOf(evt.type) < 0) return;
        const c = chunkOf(evt);
        if (!c) return;
        acc += c;
        card.classList.remove("is-loading");
        body.textContent = acc;
      });
      if (signal.aborted || !card.isConnected) return;
      if (!acc.trim()) throw new Error("no answer came back");
    } catch (e) {
      if (signal.aborted || !card.isConnected) return;
      card.classList.remove("is-loading");
      card.classList.add("is-quiet");
      body.textContent = "Thomas couldn't answer this one — " + (e && e.message || e);
    }
  }

  async function fill(page, query, openUrl, done, signal) {
    const results = page.querySelector(".bt-sr-list");
    const card = page.querySelector(".bt-ai");
    const summary = page.querySelector(".bt-sr-summary");
    let rows = [];
    let provider = "";
    try {
      const res = await fetch("/api/search/web?count=10&q=" + encodeURIComponent(query), { cache: "no-store", signal });
      const data = await res.json().catch(() => ({}));
      if (signal.aborted || !page.isConnected) return;
      if (!res.ok || !data.ok) throw new Error(data.error || "HTTP " + res.status);
      provider = typeof data.provider === "string" ? data.provider.trim() : "";
      rows = (Array.isArray(data.results) ? data.results : [])
        .filter(r => r && typeof r === "object")
        .map(r => ({ title: r.title, snippet: r.snippet, url: webUrl(r.url) }))
        .filter(r => r.url);
    } catch (e) {
      if (signal.aborted || !page.isConnected) return;
      card.remove();
      summary.textContent = "Search unavailable";
      results.innerHTML = '<div class="bt-sr-empty"><strong>Couldn’t load results</strong><p>'
        + esc(String(e && e.message || e)) + '</p><button type="button" class="bt-sr-retry">Try again</button></div>';
      results.querySelector(".bt-sr-retry").addEventListener("click", () => page.querySelector(".bt-sr-form").requestSubmit());
      results.removeAttribute("aria-busy");
      done(false);
      return;
    }
    if (signal.aborted || !page.isConnected) return;
    results.removeAttribute("aria-busy");
    summary.textContent = rows.length + (rows.length === 1 ? " result" : " results") + (provider ? " · via " + provider : "");
    if (!rows.length) {
      card.remove();
      results.innerHTML = '<div class="bt-sr-empty"><strong>No results found</strong><p>Try another search or check the spelling of ' + esc(query) + '.</p></div>';
      done(true);
      return;
    }
    results.innerHTML = rows.map(rowHTML).join("");
    results.querySelectorAll(".bt-sr-title").forEach(a => a.addEventListener("click", e => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
      e.preventDefault();
      openUrl(a.getAttribute("href"));
    }));
    done(true);
    askThomas(card, query, rows, signal);
  }

  function pageHTML(query) {
    return '<div class="bt-sr-page">'
      + '<header class="bt-sr-top"><div class="bt-sr-brand"><span class="bt-sr-mark" aria-hidden="true"><i></i><i></i></span>'
      + 'Thomas <small>SEARCH</small></div>'
      + '<form class="bt-sr-form" role="search">'
      + '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>'
      + '<input type="search" aria-label="Search the web" placeholder="Search the web" required>'
      + '<button type="submit">Search <span aria-hidden="true">↗</span></button></form></header>'
      + '<div class="bt-sr-content"><p class="bt-sr-eyebrow">The web, in Thomas</p>'
      + '<h1 class="bt-sr-q">Results for “' + esc(query) + '”</h1>'
      + '<div class="bt-sr-summary" role="status">Searching…</div>'
      + '<div class="bt-sr-main"><div class="bt-sr-list" aria-busy="true"><p class="bt-sr-loading">Finding pages…</p></div>'
      + '<section class="bt-ai is-loading" aria-live="polite">'
      + '<div class="bt-ai-head"><span class="bt-ai-spark" aria-hidden="true">✦</span>'
      + '<div><div class="bt-ai-label">Thomas overview</div><div class="bt-ai-subtitle">An answer grounded in these results</div></div></div>'
      + '<div class="bt-ai-body"></div></section></div></div></div>';
  }

  /* Where a step leaves the page it is stepping off.
   *
   * Arriving by Back puts that page *ahead* of this one, so Forward can undo
   * the step. Arriving any other way puts it *behind*, on the trail -- and a
   * fresh step ends the way ahead, the way it does in every browser: you
   * cannot go forward into a page you have just navigated away from. Arriving
   * by Forward is a walk along a record that already exists, so it ends
   * nothing.
   *
   * Reloading the page you are on is not a step anywhere, and neither is the
   * first page a new tab shows: `thomas://new-tab` is the tab's empty state,
   * not somewhere this browser can return you to.
   *
   * `native` is for a destination the desktop app will open in a WebContents-
   * View. That view owns a real history, which backStep asks first and which
   * this trail would only shadow -- the one hop it cannot know about, the
   * results page it was opened from, is kept as `searchOrigin` instead.
   */
  function recordStep(tab, url, step, native) {
    if (!tab.url || tab.url === url || tab.kind === "ntp") return;
    if (step === "back") { (tab.ahead || (tab.ahead = [])).push(tab.url); return; }
    if (!step) tab.ahead = [];
    if (!native) (tab.trail || (tab.trail = [])).push(tab.url);
  }

  /* Who owes the step back.
   *
   * In the plain browser, nobody but this chrome can. A web tab's page sits in
   * an iframe on somebody else's origin, and such a frame's `history` cannot
   * be touched from this document at all -- the property access itself throws.
   * So a step handed to the frame is a Back button that lights up and does
   * nothing, which reads as a broken browser. The pages this chrome put in
   * that frame are recorded instead (recordStep above), and they are the
   * tab's history: a tab that went results → a result → an address you typed
   * owes you that result back, not a jump over it to the results. Only once
   * the trail runs out is the results page what is left behind, and with
   * neither of those there is genuinely nowhere to go -- which the bar says
   * with a dark button.
   *
   * The desktop app is the surface with a second, real history: a web tab
   * there is a native view that keeps its own, so it is asked first, and a
   * navigation into that view records no trail to shadow it (recordStep's
   * `native`). What that view cannot know about is every page the
   * tab saw before this view existed -- the results page it was opened from
   * (`searchOrigin`), and the trail, which outlives a view because a results
   * page closes one. So the end of the view's history is not the end of the
   * tab's: once it says it cannot move, the record is asked exactly as it is
   * in the plain browser. Skipping that is how you search from a page, press
   * Back to the page, and find both buttons dark with the results gone.
   *
   * `moved` is what the surface answered when asked to go back: `undefined`
   * before anything has been asked, `false` from a desktop view that had
   * nowhere to go, `true` when it moved. A desktop build older than this
   * answers `undefined` too, so that case keeps delegating rather than
   * yanking a page out from under a history it cannot see.
   *
   * `canBack` is that same view's history as the main process last reported
   * it, which is what lets the button be *dark* instead of merely harmless:
   * asking first is a fine way to handle a click, but it cannot tell you
   * before the click whether there is anywhere to go. Only an explicit
   * `false` counts. A desktop build that never reports leaves it undefined,
   * and undefined still means "ask the view" -- exactly today's behaviour.
   */
  function backStep(tab, moved) {
    const t = tab || {};
    // A results page is a page too: search, refine the query, and the results
    // you refined away from are behind you. Nothing else can be -- a results
    // page has no frame and no native view to delegate to.
    if (t.kind === "search") return t.trail && t.trail.length ? "trail" : "none";
    if (t.kind !== "web") return "none";
    const recorded = t.trail && t.trail.length ? "trail" : (t.searchOrigin ? "search" : "none");
    if (!t.desktop) return recorded;
    if (moved === undefined) return t.canBack !== false ? "view" : recorded;
    return moved === false ? recorded : "none";
  }

  /* Who owes the step forward -- the twin of backStep, and it has to be, or
   * Back becomes a one-way door: every page Back took you off is a page
   * Forward owes you, including the result you were reading before you went
   * back to the results. That is why the results page can go forward at all,
   * and why it can do so with Back dark beside it: it is the one page in this
   * browser you reach by stepping backwards.
   *
   * "ahead" is a page this chrome itself navigated away from, recorded when
   * Back moved, and in the plain browser it is the only way forward there is
   * -- a frame on another origin cannot be stepped from here any more than it
   * can be stepped back. A desktop view is asked first exactly as Back asks
   * it, and when it answers that it has nothing ahead -- before the click via
   * `canFwd`, or after one via `moved` -- the record is asked next, exactly as
   * Back asks it. A view only ever holds the pages opened since it was made,
   * and a page Back stepped off is often older than that.
   */
  function forwardStep(tab, moved) {
    const t = tab || {};
    // A results page is rendered by this chrome on every surface, so the only
    // way forward from one is a page this chrome recorded -- exactly as
    // backStep answers for it above. Reaching the desktop branch here would
    // light Forward on a page with no native view to ask, which is the lit-
    // and-inert button this whole change exists to end, on the one page that
    // is meant to prove Back works.
    if (t.kind === "search") return t.ahead && t.ahead.length ? "ahead" : "none";
    if (t.kind !== "web") return "none";
    const recorded = t.ahead && t.ahead.length ? "ahead" : "none";
    if (!t.desktop) return recorded;
    if (moved === undefined) return t.canFwd !== false ? "view" : recorded;
    return moved === false ? recorded : "none";
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
      }
      /* Unconditionally, because a view can be *asked for* and not yet handed
       * over: attachWebFrame marks the tab desktop straight away and receives
       * its id a round trip later. Search from a result in that gap and the
       * tab would carry `desktop` onto a page that has no view, along with
       * whatever the last view reported about its history. */
      tab.desktop = false;
      tab.canBack = tab.canFwd = undefined;
    }

    function show(tab, url, step) {
      const query = queryOf(url);
      if (tab.searchController) tab.searchController.abort();
      const controller = tab.searchController = new AbortController();
      tab.webRequest = (tab.webRequest || 0) + 1;
      detach(tab);
      // Coming back here from a result: that result is what Forward owes.
      // Any other way of showing results -- a query typed in either search
      // box, a result clicked, Forward along a record -- leaves the previous
      // page behind these results. A results page is always rendered here, so
      // it never counts as a native destination.
      recordStep(tab, url, step, false);
      tab.kind = "search";
      tab.url = url;
      // Showing results IS the page Back returns to, so nothing is owed now.
      tab.searchOrigin = null;
      if (!tab.page) { tab.page = ctx.h('<div class="bt-page"></div>'); ctx.body.appendChild(tab.page); }
      tab.page.innerHTML = pageHTML(query);
      const form = tab.page.querySelector(".bt-sr-form");
      const input = form.querySelector("input");
      input.value = query;
      form.addEventListener("submit", e => {
        e.preventDefault();
        const next = input.value.trim();
        if (next) ctx.openUrl(toUrl(next));
      });
      const ic = tab.el.querySelector(".bt-tab-ic");
      if (ic) ic.innerHTML = ctx.icon;
      ctx.setTitle(tab, query);
      ctx.setStatus(tab, "working");
      ctx.activate(tab.id);
      fill(tab.page, query, ctx.openUrl,
        ok => { if (tab.searchController === controller) ctx.setStatus(tab, ok ? "done" : "error"); },
        controller.signal);
      return tab;
    }
    return { show, toUrl, looksLikeUrl, isSearchUrl, queryOf, recordStep, backStep, forwardStep };
  }

  // rowHTML and webUrl are exported because they are the two places a bad
  // result can turn into an attack; recordStep, backStep and forwardStep
  // because a navigation button that does nothing is the failure this page
  // was written to end, and the three of them are one decision split in
  // three. All five are pure enough to pin without a DOM
  // (tests/web_node/browser_search_rows.mjs).
  window.ThomasBrowserSearch = { wire, toUrl, looksLikeUrl, isSearchUrl, queryOf, webUrl, rowHTML, recordStep, backStep, forwardStep };
})();
