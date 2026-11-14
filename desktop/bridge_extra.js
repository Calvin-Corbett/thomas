/* bridge_extra.js -- the bridge verbs that let an agent use Thomas as a person
 * would, without the owner's mouse or keyboard: reach the Thomas page itself,
 * type, press keys, fill a field, read a value, take a screenshot, wait for text,
 * and close a stray window. main.js owns windows and tabs; this file only reads
 * them through what it is handed, so main.js stays small.
 */
"use strict";
const { cdpEval, cdpClick, cdpClickAx, cdpType, cdpKey, cdpScreenshot, cdpWaitForText } = require("./cdp");

module.exports = function makeExtra({ shells, tabs, currentShell, app, path, fs }) {
  /* The Thomas UI itself (chat, Build, Work) is each window's chrome page, not a
     web tab, so a tab list never showed it and no verb could reach it. Name it
     "chrome" (current window) or "chrome:<windowId>". With no tab named and no web
     tab open, a verb acts on the current window's chrome page, which is what a
     person looking at the window would be using. */
  const chromeOf = id => {
    const m = /^chrome(?::(\d+))?$/.exec(String(id));
    if (!m && !(id == null && tabs.size === 0)) return null;
    const sh = m && m[1] ? shells.get(Number(m[1])) : currentShell();
    if (!sh || !sh.chromeView || sh.chromeView.webContents.isDestroyed()) throw new Error("no such window for " + id);
    return sh.chromeView;
  };
  const chromeTabs = () => [...shells.values()]
    .filter(sh => sh.chromeView && !sh.chromeView.webContents.isDestroyed())
    .map(sh => ({
      tabId: "chrome:" + sh.id, chrome: true, windowId: sh.id,
      url: sh.chromeView.webContents.getURL(), title: sh.chromeView.webContents.getTitle(),
    }));

  const commands = (forTab, forTabInteractive) => ({
    // Typing and keys go to whatever has focus in the page, through the debugger.
    type: async p => cdpType(forTabInteractive(p.tabId), p.text),
    key: async p => cdpKey(forTabInteractive(p.tabId), p.key, p.modifiers),
    // Click a field (by role+name or CSS selector), optionally clear it, then type.
    fill: async p => {
      const view = forTabInteractive(p.tabId);
      if (p.selector) await cdpClick(view, p.selector);
      else await cdpClickAx(view, p.role, p.name);
      if (p.clear !== false) { await cdpKey(view, "a", ["ctrl"]); await cdpKey(view, "Backspace"); }
      const typed = await cdpType(view, p.text);
      if (p.submit) await cdpKey(view, "Enter");
      return Object.assign(typed, { submitted: !!p.submit });
    },
    eval: async p => ({ value: await cdpEval(forTab(p.tabId), p.expression) }),
    // A caller never chooses the folder: the name is reduced to a plain file name and the
    // file always lands in one dedicated directory (a path like ..\..\x cannot escape it).
    screenshot: async p => {
      const dir = path.join(app.getPath("temp"), "thomas-shots");
      fs.mkdirSync(dir, { recursive: true });
      const base = path.basename(String(p.file || ("shot-" + Date.now()))).replace(/[^\w.-]/g, "_");
      const file = path.join(dir, /\.jpg$/i.test(base) ? base : base + ".jpg");
      if (fs.realpathSync(path.dirname(file)) !== fs.realpathSync(dir)) throw new Error("screenshot path refused");
      if (fs.existsSync(file)) throw new Error("screenshot name already exists: " + path.basename(file));
      return cdpScreenshot(forTab(p.tabId), file);
    },
    wait_for_text: async p => cdpWaitForText(forTab(p.tabId), p.text, p.timeoutMs),
    // Close a window by id (extra windows from repeated launches).
    close_window: async p => {
      const sh = shells.get(p.windowId);
      if (!sh) throw new Error("no such window " + p.windowId);
      sh.win.close();
      return { closed: p.windowId };
    },
  });

  return { chromeOf, chromeTabs, commands };
};
