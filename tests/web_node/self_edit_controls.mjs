import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const context = { window: {} };
vm.createContext(context);
vm.runInContext(fs.readFileSync('thomas/server/web/js/self_edit_controls.js', 'utf8'), context);
const render = context.window.ThomasSelfEdit.html;
// An ordinary Build task shows no self-edit card and no scoreboard; an Edit Thomas task shows both.
assert.equal(render({ conversation: {} }), '');
const state = { activeId: 'task-a', running: false, conversation: { self_edit: true, self_edit_scope: ['thomas/a.py'], turns: [
  { run_id: 'run-a', report: { self_edit: { status: 'ready', changed_files: ['<script>'], reason: 'verified' } } }
] } };
const ready = render(state);
assert.match(ready, /Ready for review/);
assert.match(ready, /data-self-action="apply" disabled/);
assert.ok(!ready.includes('<script>'));
state.conversation.turns[0].report.self_edit.status = 'applied';
assert.match(render(state), /Runtime behavior still needs verification/);
assert.match(render(state), /Undo this run/);
state.running = true; state.runId = 'run-b';
assert.match(render(state), /Editing a private copy/);
assert.match(render(state), /Working in a private copy/);
assert.ok(!render(state).includes('Describe the improvements below'));
assert.ok(!render(state).includes('data-self-action="apply"'));
state.running = false;
state.conversation.turns = [];
assert.match(render(state), /Private self-edit task/);
assert.ok(!render(state).includes('Undo this run'));
console.log('Native self-edit UI run ownership and activation checks passed');

// The Build scoreboard shows landed comparisons and measured stage shares in the same surface.
const speedHost = { innerHTML: '', textContent: '' };
const speedRoot = { querySelector: () => speedHost };
context.document = { querySelector: () => speedHost };
context.fetch = async () => ({ ok: true, json: async () => ({ speed_scoreboard: {
  today: { median_seconds: 450, landed: 2, peak_teams: 3, steps: {
    building: 46.7, checks: 17.8, second_look: 0, repair_rounds: 12.0, card_wait: 0, unattributed: 23.5,
  } },
  last_week: { median_seconds: 1800, landed: 1, peak_teams: 1, steps: {
    building: 30, checks: 20, second_look: 5, repair_rounds: 10, card_wait: 5, unattributed: 30,
  } }, faster_percent: 75.0,
} }) });
context.window.ThomasSelfEdit.loadSpeed(speedRoot);
await new Promise(resolve => setTimeout(resolve, 0));
assert.match(speedHost.innerHTML, /7m 30s/);
assert.match(speedHost.innerHTML, /30m 0s/);
assert.match(speedHost.innerHTML, /75.0% faster than last week/);
assert.match(speedHost.innerHTML, /Teams at once: <strong>3 today<\/strong> \/ 1 last 7 days/);
assert.match(speedHost.innerHTML, /Build: <strong>46.7%<\/strong> today \/ <strong>30%<\/strong> last 7 days/);
assert.match(speedHost.innerHTML, /Repairs: <strong>12%<\/strong> today \/ <strong>10%<\/strong> last 7 days/);

// The live project list shows all five stages, escaping server-provided text.
const projectsHost = { innerHTML: '' };
context.fetch = async () => ({ ok: true, json: async () => ({ ok: true,
  slowest_today: 'Slowest today: building (100s measured)',
  unreadable: [], projects: [{ title: '<script>', state: 'done', detail: 'Measured',
    timings_seconds: { building: 100, checks: 12, second_look: 8, repair_rounds: 30, card_wait: null } }],
}) });
await context.window.ThomasSelfEdit.showProjects({ querySelector: () => projectsHost, open: true });
assert.match(projectsHost.innerHTML, /Slowest today: building \(100s measured\)/);
assert.match(projectsHost.innerHTML, /Building: 1m 40s/);
assert.match(projectsHost.innerHTML, /Checks: 12s/);
assert.match(projectsHost.innerHTML, /Second look: 8s/);
assert.match(projectsHost.innerHTML, /Repair rounds: 30s/);
assert.match(projectsHost.innerHTML, /Waiting for my card: not recorded/);
assert.ok(!projectsHost.innerHTML.includes('<script>'));

// The actual page must load the shared restart capability before its caller.
const page = fs.readFileSync('thomas/server/web/chat.html', 'utf8');
assert.ok(page.indexOf('/static/js/shell_context_menu.js?') >= 0);
assert.ok(page.indexOf('/static/js/shell_context_menu.js?') < page.indexOf('/static/js/self_edit_controls.js?'));

// A slow application keeps its honest pending reason until the server answers.
state.conversation.turns = [{ run_id: 'run-c', report: { self_edit: { status: 'ready' } } }];
let handler, finish;
context.fetch = () => new Promise(resolve => { finish = resolve; });
context.window.ThomasSelfEdit.bind({ querySelectorAll: () => [{ dataset: { selfAction: 'apply' }, addEventListener: (_name, fn) => { handler = fn; } }] }, state, () => {});
const applying = handler();
assert.match(render(state), /Applying changes: checking source files and saving originals for Undo/);
assert.match(render(state), /data-self-action="apply" disabled/);
finish({ ok: true, json: async () => ({ ok: true, status: 'applied' }) });
await applying;
assert.match(render(state), /Undo this run/);
assert.doesNotMatch(render(state), /Applying changes: checking/);

let reloads = 0;
context.window.location = { reload() { reloads++; } };
context.window.ThomasShellRestart = async () => ({ ok: false, error: 'Still restarting' });
context.window.ThomasSelfEdit.bind({ querySelectorAll: () => [{ dataset: { selfAction: 'restart' }, addEventListener: (_name, fn) => { handler = fn; } }] }, state, () => {});
await handler();
assert.equal(reloads, 0);
assert.match(render(state), /Still restarting/);
context.window.ThomasShellRestart = async () => ({ ok: true });
await handler();
assert.equal(reloads, 1);
