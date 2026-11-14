"use strict";
/* The desktop shell's startup clock and its waiting screen.
 *
 * Every launch appends one line to <profile>/startup_timing.jsonl: ms since the
 * process started, at each step a person waits through. Marks keep the first
 * time they are set, so a second window cannot rewrite the first launch's.
 * While the server is still starting the window shows a running clock, so a slow
 * start reads as "working" and says for how long, not as an empty frame. */
module.exports = function startupClock({ app, path, fs }) {
  const t0 = Date.now() - process.uptime() * 1000;
  const marks = {};
  const info = {};
  const mark = name => { if (!(name in marks)) marks[name] = Math.round(Date.now() - t0); };
  const flush = () => {
    try {
      fs.appendFileSync(path.join(app.getPath("userData"), "startup_timing.jsonl"),
        JSON.stringify({ at: new Date().toISOString(), ...info, marks }) + "\n");
    } catch (_) { }
  };
  mark("main-loaded");

  function splash(shell) {
    const wc = shell.chromeView.webContents;
    if (wc.isDestroyed()) return;
    wc.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(
      "<body style='background:#070912;color:#eef0fb;font-family:Segoe UI,sans-serif;display:grid;place-items:center;height:100vh;margin:0'>"
      + "<div style='text-align:center'><div style='font-size:34px;font-weight:600;letter-spacing:.02em'>Thomas</div>"
      + "<p style='opacity:.65;margin:10px 0 0'>Starting up&hellip; <span id=s>0</span>s</p></div>"
      + "<script>const t0=Date.now();setInterval(()=>{document.getElementById('s').textContent=Math.floor((Date.now()-t0)/1000)},250)</script></body>"));
  }

  // Run `start` (which brings the server up), showing the waiting screen if it takes more than a moment.
  async function whileStarting(shell, isUp, start) {
    mark("window-created");
    const timer = setTimeout(() => { if (!isUp()) { splash(shell); mark("splash-shown"); } }, 300);
    const up = await start();
    clearTimeout(timer);
    mark(up ? "server-up" : "server-gave-up");
    return up;
  }

  // Load the server's page into the shell, marking when it starts, becomes readable, and finishes.
  function loadShell(wc, url, origin) {
    mark("chrome-load-start");
    wc.once("dom-ready", () => mark("chrome-dom-ready"));
    const done = () => {
      if (!wc.getURL().startsWith(origin)) return;      // the waiting screen finishing is not the page
      wc.removeListener("did-finish-load", done);
      mark("chrome-loaded");
      flush();
    };
    wc.on("did-finish-load", done);
    wc.loadURL(url);
  }

  return { mark, info, whileStarting, loadShell };
};
