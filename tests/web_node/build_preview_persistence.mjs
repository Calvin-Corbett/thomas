import { app, BrowserWindow } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';

const [repo, scratch, fallback = repo] = process.argv.slice(2);
const read = name => fs.readFileSync(fs.existsSync(path.join(repo, name)) ? path.join(repo, name) : path.join(fallback, name), 'utf8');
const fixture = '<!doctype html><style>.tc-code-transcript{height:120px;overflow:auto}pre{white-space:pre-wrap}</style><div id="tc-mode-surface"></div>';
const generatedApp = '<!doctype html><label><input id="habit" type="checkbox">Water plants</label><input id="draft"><output id="state">Unchecked</output><script>document.getElementById("habit").onchange=()=>document.getElementById("state").textContent=document.getElementById("habit").checked?"Checked":"Unchecked";</script>';
const server = http.createServer((req, res) => {
  res.setHeader('Content-Type', 'text/html');
  res.end(req.url.startsWith('/app.html') ? generatedApp : fixture);
});
// This is a renderer regression check, not the operator's running Thomas app.
// No single-instance lock, production profile, server, tools, or visible window.
app.setPath('userData', path.join(scratch, 'profile'));
app.disableHardwareAcceleration();
void app.whenReady().then(async () => {
const win = new BrowserWindow({ show: false, width: 1000, height: 700,
  webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  await win.loadURL(origin);
  await win.webContents.executeJavaScript(`window.fixtureOrigin = ${JSON.stringify(origin)};`);
  await win.webContents.executeJavaScript(`
    window.ThomasUnifiedModes = {
      host: () => ({ getContext: () => ({}), renderHistory() {}, setBusy() {} }),
      registerAdapter() {}, mode: () => 'code'
    };
    window.fetch = () => Promise.reject(new Error('Unexpected network request in renderer check'));
    void 0;
  `);

  for (const name of ['view_state', 'lifecycle', 'artifacts', 'results', 'projects', 'roster', 'drawer', 'agent_chat', 'cards', 'live_diff', 'composer', 'events', 'live_view', 'surface', 'run_stream', 'questions', 'controls', 'mode']) {
    let source = read(`thomas/server/web/js/unified_code_${name}.js`);
    if (name === 'mode') source = source.replace(/\n\}\)\(\);\s*$/, `
      window.probe = { state, render, acceptStartedRun, activate() { adapterActive = true; },
        emit(event) { const replaced = pushLiveEvent(event); appendLiveEvent(event, replaced); } };
    })();`);
    await win.webContents.executeJavaScript(source);
  }
  const proof = await win.webContents.executeJavaScript(`(async () => {
    const check = (condition, message) => { if (!condition) throw new Error(message); };
    const root = document.getElementById('tc-mode-surface');
    const api = window.probe;
    const event = n => ({ type: 'tool_result', name: 'Read', event_seq: n,
      text: 'Read file ' + n + '\\n' + ('content ' + n + '\\n').repeat(8) });
    const receipt = n => [...root.querySelectorAll('.tc-code-receipt')]
      .find(node => node.querySelector('pre').textContent.startsWith('Read file ' + n + '\\n'));
    const click = detail => detail.querySelector('summary').click();
    const turn = 'renderer-check-run';
    Object.assign(api.state, { activeId: 'renderer-check-task', contextEpoch: 1,
      runId: turn, running: true, runStatus: 'working', drawerOpen: true,
      conversation: { id: 'renderer-check-task', turns: [] },
      viewer: { file: 'app.html', full: false }, artifactDocs: { 'app.html': fixtureOrigin + '/app.html' },
      liveEvents: Array.from({ length: 120 }, (_, i) => event(i + 1)) });
    api.activate(); api.render();
    const preview = root.querySelector('.tc-code-viewer-stage iframe');
    await new Promise(resolve => preview.addEventListener('load', resolve, { once: true }));
    const previewWindow = preview.contentWindow;
    const previewDocument = preview.contentDocument;
    const habit = previewDocument.getElementById('habit');
    habit.click();
    const draft = previewDocument.getElementById('draft');
    draft.value = 'An unfinished note';
    check(habit.checked && previewDocument.getElementById('state').textContent === 'Checked',
      'Fixture checkbox must run the generated app event handler');
    const detail = receipt(119);
    click(detail);
    check(detail.open, 'Clicking the real tool summary must open it');
    const transcript = root.querySelector('.tc-code-transcript');
    transcript.scrollTop = 130;
    const readingPosition = transcript.scrollTop;
    check(readingPosition > 129, 'Fixture transcript must be scrollable');
    api.emit(event(121));
    check(root.contains(preview) && preview.contentWindow === previewWindow && preview.contentDocument === previewDocument, 'Event-cap rollover replaced the interactive iframe');
    check(habit.checked && draft.value === 'An unfinished note', 'Streaming discarded the app checkbox or draft');
    habit.click();
    check(!habit.checked && previewDocument.getElementById('state').textContent === 'Unchecked', 'The same iframe must remain interactive after redraw');
    check(receipt(119) !== detail, 'The test must exercise an activity DOM redraw');
    check(receipt(119).open, 'A new event at the ring limit closed the opened tool');
    check(root.contains(preview) && preview.contentWindow === previewWindow, 'Streaming activity destroyed the Outputs preview');
    check(!receipt(120).open && !receipt(121).open, 'An unrelated tool was opened');
    check(Math.abs(root.querySelector('.tc-code-transcript').scrollTop - readingPosition) < 1, 'Reader scroll position lost');
    // Nothing folds, so an opened receipt just stays open as the feed grows.
    api.emit(event(122));
    check(receipt(119).open, 'A visible opened receipt was closed by the growing cluster');
    click(receipt(119)); api.emit(event(123));
    check(!receipt(119).open, 'An explicitly closed receipt reopened');
    api.emit(event(124));
    api.emit(event(125));
    receipt(124).querySelector('summary').focus();
    api.emit(event(126));
    check(document.activeElement === receipt(124).querySelector('summary'), 'Keyboard disclosure focus lost');
    // Same payload in a different run or conversation must not inherit state.
    receipt(123).open = true;
    api.state.runId = 'different-run'; api.render();
    check(!receipt(123).open, 'Disclosure leaked across runs');
    receipt(123).open = true;
    api.state.activeId = 'different-task'; api.state.contextEpoch++;
    api.render();
    check(!receipt(123).open, 'Disclosure leaked across task navigation');
    // Sending a follow-up paints its preparation message before the server
    // assigns the new run. The accepted identity must reach the DOM before
    // streaming starts, even when history refresh does not redraw the task.
    api.state.liveEvents = [{ type: 'planning', text: 'Preparing follow-up' }];
    api.render();
    let identityAtStreamOpen = '';
    window.EventSource = class {
      constructor() { identityAtStreamOpen = root.querySelector('[data-code-live-turn]').dataset.codeTurnKey; }
      close() {}
    };
    window.fetch = async url => {
      check(url.split('?')[0] === '/api/evolve/agent/conversations', 'Unexpected request during accepted-run check');
      return { ok: true, json: async () => ({ conversations: [] }) };
    };
    await api.acceptStartedRun({ conversation_id: api.state.activeId, run_id: 'accepted-follow-up' });
    check(identityAtStreamOpen === 'accepted-follow-up', 'Follow-up stream started under the previous run identity');
    api.emit(event(1));
    check(receipt(1).closest('[data-code-turn-key]').dataset.codeTurnKey === 'accepted-follow-up',
      'New activity belongs to the previous run in the displayed transcript');
    return { actual_app_checkbox: true, checkbox_and_draft_retained: true, same_document_interactive_after_redraw: true, ring_redraw: true, output_preview_retained: true, opened_tool_retained: true, unrelated_tools_closed: true,
      growing_cluster_retained: true, explicit_close_retained: true,
      closed_group_retained: true, open_group_retained: true, keyboard_focus_retained: true,
      run_isolation: true, task_isolation: true,
      scroll_retained: true, accepted_run_identity: true };
  })()`);
  console.log('PROOF:' + JSON.stringify(proof));
  server.close();
  app.exit(0);
} catch (error) {
  console.error(error.stack || error);
  server.close();
  app.exit(1);
}

});
