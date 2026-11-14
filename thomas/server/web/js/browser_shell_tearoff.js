/* browser_shell_tearoff.js — the title bar behaves like a browser's.
 *
 * Three things a browser window does that this one did not:
 *  - THE WINDOW MOVES. The frameless desktop window has no OS title bar, and
 *    the page's own bar was a drag region only in the few pixels between its
 *    buttons. Pressing on any empty part of the bar now drags the window
 *    (double-click maximizes), including a maximized one, which comes away
 *    from the top edge under the pointer.
 *  - TABS REORDER. Dragging a tab along the strip puts it where you let go.
 *  - TABS TEAR OFF. Pull a tab down or up off the strip and a window opens
 *    under the pointer carrying it; let go over another Thomas window's strip
 *    and the tab joins that window, as in Chrome. The window and the tab
 *    arithmetic live in the desktop app (window_geometry.js); this module owns
 *    the pointer and the strip.
 *
 * The drag uses pointer events with the pointer captured on the title bar, not
 * HTML5 drag-and-drop: a drag out of the window has to keep reporting after
 * the tab it started on has left this page, which only a capture survives.
 * Moves and releases are heard on the document, so a gesture is followed
 * wherever on the page it goes, and by the capture beyond the page.
 * In a plain browser there is no window to tear into, so only reordering runs.
 */
"use strict";

(function () {
  const DRAG_THRESHOLD = 5;       // pointer travel that turns a press into a drag
  const TEAR_DISTANCE = 28;       // how far off the strip row a tab tears out

  /* The slot a tab dragged to pointer position x lands in: the number of other
   * tabs whose midpoint it has passed. */
  function slotFor(pointerX, mids) {
    let slot = 0;
    for (const m of mids) if (pointerX > m) slot += 1;
    return slot;
  }
  function shouldTearOut(y, top, bottom) {
    return y < top - TEAR_DISTANCE || y > bottom + TEAR_DISTANCE;
  }
  /* A press on the bar moves the window unless it lands on something that
   * does a job of its own. */
  function isWindowHandle(target, titlebar) {
    if (!target || typeof target.closest !== "function" || !titlebar.contains(target)) return false;
    return !target.closest("button, input, a, .bt-tab, .bt-wincluster");
  }

  /* Calls fn with the latest arguments at most once per animation frame, and
   * never while the previous call is still waiting on the app. */
  function latestOnly(fn) {
    let pending = null;
    let busy = false;
    let scheduled = false;
    const flush = () => {
      scheduled = false;
      if (busy || !pending) return;
      const args = pending;
      pending = null;
      busy = true;
      Promise.resolve(fn(...args)).catch(() => { }).then(() => {
        busy = false;
        if (pending && !scheduled) { scheduled = true; requestAnimationFrame(flush); }
      });
    };
    const push = (...args) => {
      pending = args;
      if (!scheduled && !busy) { scheduled = true; requestAnimationFrame(flush); }
    };
    push.drain = () => { pending = null; };
    return push;
  }

  function wire(ctx) {
    const { desktop, titlebar, strip, newBtn } = ctx;

    /* ── Moving the window ──────────────────────────────────────────── */
    if (desktop && desktop.dragWindow) {
      let moving = null;                        // pointerId while a window drag runs
      const sendMove = latestOnly((x, y) => desktop.dragWindow("move", x, y));
      titlebar.addEventListener("pointerdown", e => {
        if (e.button !== 0 || moving !== null || !isWindowHandle(e.target, titlebar)) return;
        moving = e.pointerId;
        try { titlebar.setPointerCapture(e.pointerId); } catch (_) { }
        desktop.dragWindow("start", e.screenX, e.screenY);
      });
      document.addEventListener("pointermove", e => {
        if (moving === e.pointerId) sendMove(e.screenX, e.screenY);
      }, true);
      const stop = e => {
        if (moving !== e.pointerId) return;
        moving = null;
        sendMove.drain();
        desktop.dragWindow("end", e.screenX, e.screenY);
      };
      document.addEventListener("pointerup", stop, true);
      document.addEventListener("pointercancel", stop, true);
      titlebar.addEventListener("dblclick", e => {
        if (isWindowHandle(e.target, titlebar)) desktop.windowControl("max");
      });
    }

    /* ── Dragging a tab ─────────────────────────────────────────────── */
    let armed = null;      // { tab, pointerId, x, y }: pressed, not yet moved far enough
    let drag = null;       // { tab, pointerId, state: "reorder" | "detaching" | "torn" }
    let justDragged = false;
    const sendTabMove = latestOnly((x, y) => desktop.dragTab("move", null, x, y));

    function otherMids(tab) {
      return ctx.getTabs().filter(t => t !== tab).map(t => {
        const r = t.el.getBoundingClientRect();
        return r.left + r.width / 2;
      });
    }
    function reorderTo(tab, pointerX) {
      const others = ctx.getTabs().filter(t => t !== tab);
      // The home tab keeps the first place: a tab dragged left stops after it.
      const slot = Math.max(slotFor(pointerX, otherMids(tab)), others.filter(t => t.pinned).length);
      const before = others[slot] ? others[slot].el : newBtn;
      if (tab.el.nextElementSibling !== before) strip.insertBefore(tab.el, before);
      ctx.reorderTabs(Array.from(strip.querySelectorAll(".bt-tab")));
    }
    function beginDrag(e) {
      const tab = armed.tab;
      drag = { tab, state: "reorder", pointerId: e.pointerId, ended: null };
      tab.el.classList.add("is-dragging");
      strip.classList.add("is-reordering");
    }
    async function tearOff(e) {
      const d = drag;
      const spec = desktop && desktop.dragTab ? ctx.specFor(d.tab) : null;
      if (!spec) return;                         // this kind of tab stays on its strip
      d.state = "detaching";
      let opened = null;
      try { opened = await desktop.dragTab("detach", spec, e.screenX, e.screenY); } catch (_) { opened = null; }
      if (drag !== d) return;
      if (opened == null) { d.state = "reorder"; if (d.ended) finish(d.ended); return; }
      d.state = "torn";
      d.tab.el.classList.remove("is-dragging");
      strip.classList.remove("is-reordering");
      // The tab now lives in the new window: leave it here without closing it.
      ctx.releaseTab(d.tab);
      if (d.ended) finish(d.ended);              // let go while the window was opening
    }
    function finish(e) {
      const d = drag;
      if (!d) return;
      if (d.state === "detaching") { d.ended = e; return; }
      drag = null;
      try { titlebar.releasePointerCapture(d.pointerId); } catch (_) { }
      d.tab.el.classList.remove("is-dragging");
      strip.classList.remove("is-reordering");
      if (d.state === "torn") {
        sendTabMove.drain();
        // Once the app has settled where the tab went, a window that was only
        // ever holding it (nothing but its home tab left) has no reason to stay.
        Promise.resolve(desktop.dragTab("end", null, e.screenX, e.screenY))
          .catch(() => { }).then(() => { if (ctx.afterTear) ctx.afterTear(); });
      } else {
        ctx.activate(d.tab.id);
      }
      justDragged = true;
      setTimeout(() => { justDragged = false; }, 0);
    }

    strip.addEventListener("pointerdown", e => {
      if (e.button !== 0 || drag || armed) return;
      const el = e.target.closest ? e.target.closest(".bt-tab") : null;
      if (!el || e.target.closest(".bt-tab-x")) return;
      const tab = ctx.getTabs().find(t => t.el === el);
      if (!tab || tab.pinned) return;
      armed = { tab, pointerId: e.pointerId, x: e.clientX, y: e.clientY };
      // Held from the first press: a quick pull can leave the bar before its
      // second pointer event, and only a capture keeps the gesture ours. The
      // click then lands on the bar, so release() activates a plain click.
      try { titlebar.setPointerCapture(e.pointerId); } catch (_) { }
    });
    document.addEventListener("pointermove", e => {
      if (armed && armed.pointerId === e.pointerId && !drag) {
        if (Math.hypot(e.clientX - armed.x, e.clientY - armed.y) < DRAG_THRESHOLD) return;
        beginDrag(e);
        armed = null;
      }
      if (!drag || drag.pointerId !== e.pointerId) return;
      if (drag.state === "torn") { sendTabMove(e.screenX, e.screenY); return; }
      if (drag.state !== "reorder") return;
      const row = strip.getBoundingClientRect();
      if (desktop && shouldTearOut(e.clientY, row.top, row.bottom)) tearOff(e);
      else reorderTo(drag.tab, e.clientX);
    }, true);
    const release = e => {
      if (armed && armed.pointerId === e.pointerId) {
        // Pressed and let go without travelling: that was a click on the tab.
        const tab = armed.tab;
        armed = null;
        try { titlebar.releasePointerCapture(e.pointerId); } catch (_) { }
        if (e.type === "pointerup") ctx.activate(tab.id);
        justDragged = true;                    // the click that follows lands on the bar
        setTimeout(() => { justDragged = false; }, 0);
      }
      if (drag && drag.pointerId === e.pointerId) finish(e);
    };
    document.addEventListener("pointerup", release, true);
    document.addEventListener("pointercancel", release, true);
    // The click that ends a drag must not also activate or close something.
    titlebar.addEventListener("click", e => { if (justDragged) { e.stopPropagation(); e.preventDefault(); } }, true);

    /* ── Receiving a tab ────────────────────────────────────────────── */
    if (desktop && desktop.onAdopt) desktop.onAdopt(spec => ctx.adopt(spec));
    if (desktop && desktop.onStripHover) {
      desktop.onStripHover(on => strip.classList.toggle("is-drop-target", on));
    }
  }

  window.ThomasBrowserTearoff = { wire, slotFor, shouldTearOut, isWindowHandle, latestOnly };
}());
