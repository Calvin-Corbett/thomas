/* browser_shell_keys.js — the conventions your hands already know.
 *
 * A tab strip that looks like tabs but does not answer Ctrl+T is a picture of
 * a browser. These are the Chrome bindings, unchanged, because the whole
 * point is that nobody should have to learn them:
 *
 *   Ctrl+T            new tab            Ctrl+W           close this tab
 *   Ctrl+Tab          next tab           Ctrl+Shift+Tab   previous tab
 *   Ctrl+1..8         nth tab            Ctrl+9           last tab
 *   Ctrl+L / Alt+D    focus the omnibox  Ctrl+R / F5      reload
 *   Alt+Left/Right    back / forward
 *
 * In a plain browser tab, Chrome and Edge keep Ctrl+T, Ctrl+W, Ctrl+Tab,
 * Ctrl+Shift+Tab and Ctrl+PageUp/PageDown for their OWN tabs: the page never
 * sees them, and we do not fight that. Ctrl+1..9, Ctrl+L, Ctrl+R, F5, Alt+D
 * and Alt+arrows do reach the page. So the strip also answers bindings the
 * browser leaves alone, and those work in every runtime:
 *
 *   Alt+1..9                    nth tab (9 is the last)
 *   Alt+PageDown / Alt+PageUp   next / previous tab
 *
 * No Ctrl+Shift combination, on purpose: the layout editor (ui_edit_mode.js)
 * treats a Ctrl+Shift press-and-release as the chord that toggles Redesign
 * mode, and a listener that swallows the key in between leaves the chord
 * armed, so the editor switched itself on inside every tab document and its
 * click layer ate every click there. Verified in a browser on 2026-09-01.
 *
 * A binding whose action does nothing (back on a chat tab, next tab with one
 * tab open, closing the pinned home) returns false and leaves the browser's
 * own default alone instead of swallowing it.
 *
 * Two routes in, one implementation. The keydown listener handles keys while
 * a Thomas page has focus; attachTo() installs the same listener on each tab
 * document, because a keydown inside an iframe never reaches the parent. In
 * the desktop app a focused web tab is a separate renderer, so the main
 * process forwards the ACTION for the keys that view swallowed.
 */
"use strict";

(function () {
  function wire(ctx) {
    const { newTab, closeActiveTab, cycleTab, selectTabIndex, focusOmnibox,
      reloadActive, goBack, goForward } = ctx;

    const ACTIONS = {
      "new-tab": newTab,
      "close-tab": closeActiveTab,
      "next-tab": () => cycleTab(1),
      "prev-tab": () => cycleTab(-1),
      "focus-omnibox": focusOmnibox,
      "reload": reloadActive,
      "back": goBack,
      "forward": goForward,
    };

    // True when the action did something. A callback that returns false is
    // a no-op, and a no-op never cancels the browser's own default.
    function handle(action, arg) {
      if (action === "select-tab") return selectTabIndex(arg) !== false;
      const fn = ACTIONS[action];
      if (!fn) return false;
      return fn() !== false;
    }

    // Which action, if any, a key event means. Returns null for everything
    // else, so ordinary typing is never disturbed.
    function actionFor(e) {
      const ctrl = e.ctrlKey || e.metaKey;
      const altGraph = typeof e.getModifierState === "function" && e.getModifierState("AltGraph");
      if (ctrl && !e.altKey) {
        const key = String(e.key || "").toLowerCase();
        if (key === "t" && !e.shiftKey) return ["new-tab"];
        if (key === "w" && !e.shiftKey) return ["close-tab"];
        if (key === "l" && !e.shiftKey) return ["focus-omnibox"];
        if (key === "r" && !e.shiftKey) return ["reload"];
        if (e.key === "Tab") return [e.shiftKey ? "prev-tab" : "next-tab"];
        if (/^[1-9]$/.test(e.key) && !e.shiftKey) return ["select-tab", Number(e.key)];
      }
      if (e.altKey && !ctrl && !altGraph) {
        if (e.key === "ArrowLeft") return ["back"];
        if (e.key === "ArrowRight") return ["forward"];
        if (String(e.key || "").toLowerCase() === "d") return ["focus-omnibox"];
        // Option+digit types symbols on a Mac keyboard, so the digit row is
        // Windows and Linux only; e.code keeps numpad Alt-codes out of it.
        if (/^Digit[1-9]$/.test(String(e.code || "")) && !/Mac/.test(String(navigator.platform || ""))) {
          return ["select-tab", Number(String(e.code).slice(5))];
        }
        if (e.key === "PageDown") return ["next-tab"];
        if (e.key === "PageUp") return ["prev-tab"];
      }
      if (e.key === "F5" && !ctrl && !e.altKey) return ["reload"];
      return null;
    }

    function listener(e) {
      const hit = actionFor(e);
      if (!hit) return;
      if (handle(hit[0], hit[1])) {
        e.preventDefault();
        e.stopPropagation();
      }
    }
    function attachTo(win) { win.addEventListener("keydown", listener, true); }
    attachTo(window);

    // The honest table, for the + page: which bindings work in a plain
    // browser tab and which only the desktop app can answer.
    function bindings() {
      return [
        { keys: "Ctrl+1..9", does: "that tab (9 is the last)", everywhere: true },
        { keys: "Alt+1..9", does: "that tab", everywhere: true },
        { keys: "Alt+PageDown / Alt+PageUp", does: "next / previous tab", everywhere: true },
        { keys: "Ctrl+L / Alt+D", does: "the address bar", everywhere: true },
        { keys: "Ctrl+Tab / Ctrl+Shift+Tab", does: "next / previous tab", everywhere: false },
        { keys: "Ctrl+T / Ctrl+W", does: "new / close tab", everywhere: false },
      ];
    }

    return { handle, actionFor, attachTo, bindings };
  }

  window.ThomasBrowserKeys = { wire };
}());
