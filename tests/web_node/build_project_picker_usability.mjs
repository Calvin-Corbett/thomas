import { app, BrowserWindow } from 'electron';
import fs from 'node:fs';
import path from 'node:path';

const [repo, scratch, fallback = repo] = process.argv.slice(2);
const source = name => fs.readFileSync(fs.existsSync(path.join(repo, name)) ? path.join(repo, name) : path.join(fallback, name), 'utf8');
app.setPath('userData', path.join(scratch, 'profile'));
app.disableHardwareAcceleration();
void app.whenReady().then(async () => {
const win = new BrowserWindow({ show: false, width: 1000, height: 700,
  webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
try {
  const page = path.join(scratch, 'fixture.html');
  fs.writeFileSync(page, '<!doctype html><div id="tc-shell"><input id="tc-input"><button id="tc-code-project-btn"></button><div id="tc-code-project-wrap"><div id="tc-code-library-menu"></div></div><div id="tc-mode-surface"></div></div>');
  await win.loadFile(page);
  await win.webContents.executeJavaScript(`
    window.requests = []; window.pendingCreate = null; window.holdCreate = false; window.failCreate = false;
    window.prompt = () => { throw new Error('Native prompts cannot be used by this embedded browser'); };
    window.fetch = async (url, options = {}) => {
      const reply = (data, status = 200) => ({ ok: status < 400, status, json: async () => data, headers: { get: () => 'application/json' } });
      if (url === '/api/evolve/agent/conversations/new') {
        const body = JSON.parse(options.body); requests.push(body);
        if (holdCreate) await new Promise(resolve => { window.pendingCreate = resolve; });
        if (failCreate) return reply({ ok: false, error: 'Project creation unavailable' }, 503);
        return reply({ ok: true, conversation: { id: 'created-' + requests.length, project_root: '/fixture/' + (body.new_project_name || 'scratch'), turns: [] } });
      }
      if (url.split('?')[0] === '/api/evolve/agent/conversations') return reply({ conversations: [] });
      if (url === '/api/local/projects') return reply({ ok: true, projects: [] });
      if (url.startsWith('/api/evolve/agent/conversations/') && url.endsWith('/tree')) return reply({ ok: true, entries: [] });
      if (url.startsWith('/api/evolve/agent/status')) return reply({ ok: true, running: false });
      if (url === '/api/issues') return reply({ ok: true });
      throw new Error('Unexpected request: ' + url);
    }; void 0;
  `);
  for (const name of ['unified_mode_shell', 'unified_code_view_state', 'unified_code_lifecycle', 'unified_code_artifacts', 'unified_code_results', 'unified_code_projects', 'unified_code_roster', 'unified_code_drawer', 'unified_code_agent_chat', 'unified_code_cards', 'unified_code_live_diff', 'unified_code_composer', 'unified_code_events', 'unified_code_live_view', 'unified_code_surface', 'unified_code_run_stream', 'unified_code_questions', 'unified_code_controls', 'unified_code_mode', 'chat_composer_panels']) {
    let js = source(`thomas/server/web/js/${name}.js`);
    if (name === 'unified_code_mode') js = js.replace(/\n\}\)\(\);\s*$/, '\nwindow.buildProbe = { state, render };\n})();');
    await win.webContents.executeJavaScript(js);
  }
  await win.webContents.executeJavaScript(`
    window.ThomasUnifiedModes.connect({ getContext: () => ({ modelId: 'gpt-5.6-luna' }), renderHistory() {}, setBusy() {} });
    window.pickerState = {}; window.inputEl = document.getElementById('tc-input');
    window.picker = window.ThomasChatComposerPanels.create({ state: pickerState, inputEl,
      esc: value => String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])),
      autosize() {}, syncDynamic() {}, DIAL_FIELDS: [], saveDials() {} });
    Object.assign(window, picker); void 0;
  `);
  const html = source('thomas/server/web/chat.html');
  const start = html.indexOf("    document.getElementById('tc-code-library-menu').addEventListener('click'");
  const wire = start >= 0 ? html.slice(start, html.indexOf("    document.getElementById('tc-code-library-menu').addEventListener('input'", start)) : 'bindLibraryActions();';
  await win.webContents.executeJavaScript(wire);
  const proof = await win.webContents.executeJavaScript(`(async () => {
    const proof = window.proof = {}, check = (name, value) => { proof[name] = !!value; };
    const settle = () => new Promise(resolve => setTimeout(resolve, 20));
    check('entered_build', await ThomasUnifiedModes.setMode('code'));
    // Use both shipped adapters and the real project owner; only HTTP is replaced.
    holdCreate = true;
    const pending = ThomasUnifiedModes.newConversation('', 'Adapter Name', { newProjectName: 'Adapter Name' });
    check('shell_returns_pending_promise', !!pending && typeof pending.then === 'function');
    check('options_reach_creation_route', requests.at(-1).new_project_name === 'Adapter Name');
    pendingCreate(); holdCreate = false; await pending; await settle();
    pickerState.libraryProjects = []; picker.toggleLibraryMenu();
    document.querySelector('[data-lib-action="new"]').click();
    let field = document.getElementById('tc-library-project-name');
    check('new_project_shows_in_page_form', pickerState.libraryMenuOpen && !!field);
    if (field) {
      check('name_field_receives_focus', document.activeElement === field);
      const beforeCancel = requests.length;
      document.querySelector('[data-lib-action="cancel-new"]').click();
      check('cancel_returns_to_library_without_creating', requests.length === beforeCancel && pickerState.libraryMenuOpen && !document.getElementById('tc-library-project-name'));
      document.querySelector('[data-lib-action="new"]').click();
      field = document.getElementById('tc-library-project-name');
      field.value = '   '; field.dispatchEvent(new Event('input', { bubbles: true }));
      document.getElementById('tc-library-new-project').requestSubmit();
      check('blank_name_stays_in_form_without_request', requests.length === beforeCancel && document.querySelector('[role="status"]').textContent === 'Enter a project name.');
      field = document.getElementById('tc-library-project-name');
      field.value = '  Lantern Luna Proof  '; field.dispatchEvent(new Event('input', { bubbles: true }));
      // A library fetch finishing while the form is open must preserve the draft.
      picker.renderLibraryMenu();
      check('library_refresh_keeps_name_draft', document.getElementById('tc-library-project-name').value === '  Lantern Luna Proof  ');
      holdCreate = true; const beforeSubmit = requests.length;
      document.getElementById('tc-library-new-project').requestSubmit();
      check('exact_name_reaches_server', requests.at(-1).new_project_name === 'Lantern Luna Proof');
      check('pending_creation_stays_visible', pickerState.libraryMenuOpen && document.querySelector('#tc-library-new-project button[type="submit"]').disabled);
      document.getElementById('tc-library-new-project').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      check('duplicate_submission_sends_once', requests.length === beforeSubmit + 1);
      pendingCreate(); holdCreate = false; await settle();
      check('success_selects_exact_new_folder', buildProbe.state.projectRoot === '/fixture/Lantern Luna Proof' && buildProbe.state.chosenProjectRoot === '/fixture/Lantern Luna Proof');
      check('success_closes_form_and_focuses_composer', !pickerState.libraryMenuOpen && document.activeElement === inputEl);
      pickerState.libraryProjects = []; picker.toggleLibraryMenu();
      document.querySelector('[data-lib-action="new"]').click();
      field = document.getElementById('tc-library-project-name');
      field.value = 'Retry Project'; field.dispatchEvent(new Event('input', { bubbles: true }));
      failCreate = true; document.getElementById('tc-library-new-project').requestSubmit(); await settle();
      check('failure_retains_form_and_name', pickerState.libraryMenuOpen && document.getElementById('tc-library-project-name').value === 'Retry Project');
      check('failure_is_visible_and_retry_enabled', document.querySelector('[role="status"]').textContent.includes('Could not create') && !document.querySelector('#tc-library-new-project button[type="submit"]').disabled);
      failCreate = false; document.getElementById('tc-library-new-project').requestSubmit(); await settle();
      check('retry_uses_same_name_and_closes', requests.at(-1).new_project_name === 'Retry Project' && !pickerState.libraryMenuOpen);
    }
    return proof;
  })()`);
  console.log('PROOF:' + JSON.stringify(proof));
  if (Object.values(proof).some(value => !value)) process.exitCode = 1;
} catch (error) { console.error(error); console.log('PARTIAL:' + JSON.stringify(await win.webContents.executeJavaScript('({ proof: window.proof, requests: window.requests, html: document.getElementById("tc-code-library-menu").innerHTML })'))); process.exitCode = 1; }
finally { win.destroy(); app.exit(process.exitCode || 0); }
});
