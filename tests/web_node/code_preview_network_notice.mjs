// The preview must SAY when it is the reason a page's network calls fail.
//
// Measured (w2-code-network, w2-code-impossible): the artifact preview CSP
// blocks all outbound connections beside the chat, so a perfectly working
// generated app opens straight into its own error state -- "Live feed
// unavailable", "Google sign-in is still loading" -- and nothing anywhere says
// the PREVIEW is the reason. The fix is sight, not a gate: detect that the
// page asks for the network and put one visible line on the viewer saying the
// embedded preview blocks internet access, next to the existing
// open-in-its-own-tab affordance (whose standalone document IS allowed
// outbound https by the server).
//
// This harness drives the real thomas/server/web/js/unified_code_results.js in
// a vm: the detector's judgement on network-shaped and network-free documents,
// the flag being learned while the doc is resolved (ensureArtifactDoc), and
// the notice actually appearing on the viewer surface.
import fs from 'node:fs';
import vm from 'node:vm';

const modulePath = process.argv[2];
if (!modulePath) throw new Error('usage: node code_preview_network_notice.mjs <unified_code_results.js>');
const moduleSource = fs.readFileSync(modulePath, 'utf8');

const checks = {};

function boot(fileContent) {
  const state = { activeId: 'c1', artifactDocs: {}, viewer: null };
  const context = {
    window: {},
    console,
    // ensureArtifactDoc resolves the preview origin, then readProjectFile
    // pulls the page's own text through the validated read.
    fetch: async (url) => {
      if (String(url).includes('/preview?')) {
        return { ok: true, json: async () => ({ ok: true, url: 'http://127.0.0.1:1/cap/app.html' }) };
      }
      if (String(url).includes('/file?')) {
        return { ok: true, json: async () => ({ ok: true, content: fileContent }) };
      }
      throw new Error(`unexpected fetch: ${url}`);
    },
  };
  vm.createContext(context);
  vm.runInContext(moduleSource, context);
  const api = context.window.ThomasCodeResults;
  api.configure({
    state,
    esc: (s) => String(s),
    isInternalResultPath: () => false,
    lifecycle: () => ({ contextToken: () => ({ id: 'c1' }), contextMatches: () => true }),
    render: () => {},
  });
  return { api, state };
}

// ---- 1. the detector's judgement ----
const probe = boot('');
const wants = probe.api.htmlWantsNetwork;
checks.detectorExported = typeof wants === 'function';
if (checks.detectorExported) {
  checks.flagsFetch = wants('<script>fetch("https://api.example.com/feed")</script>') === true;
  checks.flagsRelativeFetch = wants('<script>fetch("/api/data")</script>') === true;
  checks.flagsXhr = wants('<script>const r = new XMLHttpRequest();</script>') === true;
  checks.flagsWebSocket = wants('<script>new WebSocket("wss://x.example/ws")</script>') === true;
  checks.flagsEventSource = wants('<script>new EventSource("/events")</script>') === true;
  checks.flagsExternalScript = wants('<script src="https://accounts.google.com/gsi/client"></script>') === true;
  checks.flagsExternalStylesheet = wants('<link rel="stylesheet" href="https://cdn.example.com/a.css">') === true;
  checks.flagsExternalImage = wants('<img src="https://example.com/pic.png">') === true;
  // A self-contained page must NOT be nagged about the network.
  checks.quietOnPlainPage = wants('<html><body><h1>snake</h1><script>let s = 1 + 1;</script></body></html>') === false;
  // The word "fetched" in prose, an outbound <a> link, and a local script are
  // not network use -- an anchor navigates, it does not connect.
  checks.quietOnProseAndLinks = wants(
    '<p>data is fetched daily</p><a href="https://example.com">source</a><script src="game.js"></script>',
  ) === false;
}

// ---- 2. the flag is learned while the doc is resolved ----
const live = boot('<script>fetch("https://api.example.com/live")</script>');
await live.api.ensureArtifactDoc('app.html', true);
checks.docResolved = live.state.artifactDocs['app.html'] === 'http://127.0.0.1:1/cap/app.html';
checks.networkFlagLearned = !!(live.state.artifactNet && live.state.artifactNet['app.html'] === true);

const still = boot('<html><body>no network here</body></html>');
await still.api.ensureArtifactDoc('app.html', true);
checks.quietFlagLearned = !!(still.state.artifactNet && still.state.artifactNet['app.html'] === false);

// ---- 3. the notice is on the viewer surface, beside the open-in-tab way out ----
live.state.viewer = { file: 'app.html' };
const noisyViewer = live.api.viewerHtml();
checks.noticeShown = /blocks internet access/i.test(noisyViewer);
checks.noticeNamesTheWayOut = /own tab/i.test(noisyViewer);
// The existing escape hatch must be right there for the notice to point at.
checks.openInTabStillPresent = noisyViewer.includes('/api/evolve/agent/artifact/c1/app.html');

still.state.viewer = { file: 'app.html' };
const quietViewer = still.api.viewerHtml();
checks.noNoticeOnQuietPage = !/blocks internet access/i.test(quietViewer);

const failures = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
if (failures.length > 0) throw new Error(`preview network notice checks failed: ${failures.join(', ')}`);
process.stdout.write(`${JSON.stringify(checks)}\n`);
