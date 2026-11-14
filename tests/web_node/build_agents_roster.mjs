// Build's agents, fed the frames a real run writes: the lead (no agent_id), a
// task.spawn read-only helper and a task.team builder (agent_id child_<12hex>,
// "[Title] " text, "Title > tool" names, lifecycle only in text), and a
// server-run helper (agent_spawned / agent_status / agent_event with
// agent_state). Checks the roster, the bot, the drawer and the side chat in the
// shipped modules, loaded the way chat.html loads them.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const js = name => path.join(root, 'thomas', 'server', 'web', 'js', name);
const context = { window: {}, console, Date, Math, JSON, Number, String, Array, Set, Map };
vm.createContext(context);
for (const file of ['thomas_bot.js', 'chat_theme_controls.js', 'unified_code_roster.js', 'unified_code_drawer.js', 'unified_code_agent_chat.js']) {
  vm.runInContext(fs.readFileSync(js(file), 'utf8'), context, { filename: file });
}
const { ThomasBot, ThomasChatThemeControls, ThomasCodeRoster, ThomasCodeDrawer, ThomasCodeAgentChat } = context.window;
const esc = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const checks = [];
const check = (name, fn) => { fn(); checks.push(name); };
// The modules run in their own realm, so their arrays are not this realm's;
// compare values, not prototypes.
const plain = value => JSON.parse(JSON.stringify(value));
const same = (actual, expected, message) => assert.deepStrictEqual(plain(actual), plain(expected), message);
const notSame = (actual, expected, message) => assert.notDeepStrictEqual(plain(actual), plain(expected), message);

// ---------- ThomasBot ----------
check('the bot drawing moved, and the theme controls draw it through ThomasBot', () => {
  const hero = { primary: 'var(--bot-primary)', secondary: 'var(--bot-secondary)', trim: 'var(--bot-trim)', glow: 'var(--bot-glow)', scale: '1.4', flame: 'true' };
  const drawn = ThomasBot.markup(hero);
  assert.match(drawn, /width: 58px; height: 54px; image-rendering: pixelated; transform: scale\(1\.4\)/);
  assert.match(drawn, /drop-shadow\(0 8px 16px var\(--bot-glow\)\)/);
  assert.match(drawn, /animation: bot-flame/, 'the flame still draws when asked for');
  assert.equal((drawn.match(/animation: bot-blink 4\.6s/g) || []).length, 2);
  assert.equal((drawn.match(/class="tb-leg tb-leg-[lr]"/g) || []).length, 2);
  assert.doesNotMatch(ThomasBot.markup({ ...hero, flame: false }), /bot-flame/);
  const controls = ThomasChatThemeControls.create({});
  assert.equal(controls.botHTML(hero), drawn);
  const source = fs.readFileSync(js('chat_theme_controls.js'), 'utf8');
  assert.doesNotMatch(source, /image-rendering: pixelated/, 'chat_theme_controls.js keeps no second copy of the drawing');
});

check('an agent bot is boxed, sized, coloured by name and moved by state', () => {
  const lead = ThomasBot.html({ state: 'working', seed: 'thomas', size: 'md' });
  assert.match(lead, /^<span class="tb-box tb-md is-working" aria-hidden="true"><span class="tb-motion">/);
  assert.match(lead, /#9ad8ff/, 'the lead is the blue bot');
  assert.match(lead, /scale\(0\.44\)/);
  assert.match(ThomasBot.html({ state: 'waiting', seed: 'verifier', size: 'sm' }), /tb-sm is-waiting[\s\S]*scale\(0\.3\)[\s\S]*#ffd98a/);
  assert.match(ThomasBot.html({ state: 'nonsense', seed: 'x', size: 'huge' }), /tb-box tb-md is-idle/);
  same([...ThomasBot.colours('Scout')], [...ThomasBot.colours('scout')], 'a name keeps its colour');
  notSame([...ThomasBot.colours('Scout')], [...ThomasBot.colours('thomas')]);
});

// ---------- Roster ----------
const T0 = 1_761_700_000_000;
let clock = T0;
const at = (ms) => { clock = T0 + ms; return clock; };
const SCOUT = { agent_id: 'child_0123456789ab', agent_title: 'Scout', agent_mode: 'read_only', model: 'gpt-5.6-mini' };
const WIRER = { agent_id: 'child_a1b2c3d4e5f6', agent_title: 'Wirer', agent_mode: 'builder', model: 'gpt-5.6-luna' };
const REVIEW = { agent_id: 'agent_0123456789abcdef01234567', agent_title: 'Reviewer' };
const lead = frame => ({ type: 'output', ...frame });
const child = (who, frame) => ({ type: 'output', ...who, ...frame });

const roster = ThomasCodeRoster.create();
const frames = [
  lead({ kind: 'meta', receipt: 'model', model: 'gpt-5.6-luna', text: 'Ran on gpt-5.6-luna', ts: at(0) }),
  lead({ kind: 'say', text: 'I will split this so nothing waits. ', delta: true, ts: at(400) }),
  lead({ kind: 'say', text: '[Scout] maps the colours.', delta: true, ts: at(500) }),
  lead({ kind: 'plan', text: '1 of 3 done', ts: at(900), items: [
    { id: 'p1', text: 'Map where colours are set', status: 'completed', owner: 'Scout' },
    { id: 'p2', text: 'Corner toggle', status: 'in_progress', owner: 'Wirer' },
    { id: 'p3', text: 'Check every ask', status: 'pending', owner: '' },
  ] }),
  lead({ kind: 'tool_started', name: 'task.spawn', text: '{"title": "Scout", "instructions": "Map where colours are set in `styles.css` and index.html.\\nList each one."}', ts: at(1000) }),
  child(SCOUT, { kind: 'meta', text: '[Scout] Spawned Scout — read-only source review · gpt-5.6-mini', is_error: false, ts: at(1100) }),
  child(SCOUT, { kind: 'tool_started', name: 'Scout > fs.read_file', text: '[Scout] path: index.html', path: 'index.html', ts: at(1200) }),
  child(SCOUT, { kind: 'tool_result', name: 'Scout > fs.read_file', text: '[Scout] <!doctype html>\npath: not/a/file.css\nWrote 9 chars to nowhere.txt', is_error: false, path: 'index.html', ts: at(1900) }),
  child(SCOUT, { kind: 'say', text: '\n[Scout] Found 3', delta: true, ts: at(2000) }),
  child(SCOUT, { kind: 'say', text: ' hard-coded colours.', delta: true, ts: at(2100) }),
  child(SCOUT, { kind: 'meta', text: '[Scout] Found 3 hard-coded colours: #fff and #1d2330 in styles.css.', ts: at(9000) }),
  child(SCOUT, { kind: 'meta', text: '[Scout] Scout finished', ts: at(10000) }),
  lead({ kind: 'tool_result', name: 'task.spawn', text: 'Found 3 hard-coded colours', is_error: false, ts: at(10100) }),
  lead({ kind: 'tool_started', name: 'task.team', text: '{"assignments": [{"title": "Wirer", "path": "app.js", "instructions": "Add button#theme in the header and persist the choi', ts: at(11000) }),
  child(WIRER, { kind: 'meta', text: '[Wirer] Spawned Wirer — isolated file builder · gpt-5.6-luna', ts: at(11100) }),
  child(WIRER, { kind: 'tool_started', name: 'Wirer > fs.write_file', text: '[Wirer] path: app.js', ts: at(12000) }),
  child(WIRER, { kind: 'tool_result', name: 'Wirer > fs.write_file', text: '[Wirer] Wrote 512 chars to app.js', is_error: false, ts: at(13000) }),
  child(WIRER, { kind: 'tool_started', name: 'Wirer > diff.create', text: '[Wirer] path: index.html', path: 'index.html', ts: at(14000) }),
  child(WIRER, { kind: 'tool_result', name: 'Wirer > diff.create', text: '[Wirer] Replaced 1 line(s) with 9 line(s) in index.html', path: 'index.html', added: 9, removed: 1, is_error: false, ts: at(15000) }),
  child(WIRER, { kind: 'tool_started', name: 'Wirer > fs.read_file', text: '[Wirer] path: app.js', path: 'app.js', ts: at(16000) }),
];
frames.forEach(frame => roster.feed(frame));
clock = T0 + 20000;
const realNow = Date.now;
context.Date.now = () => clock;

check('the lead comes first, named Thomas, with the model that answered', () => {
  const list = roster.agents();
  same(list.map(agent => agent.id), ['lead', SCOUT.agent_id, WIRER.agent_id]);
  assert.equal(list[0].name, 'Thomas');
  assert.equal(list[0].role, 'lead');
  assert.equal(list[0].model, 'gpt-5.6-luna');
  assert.equal(roster.count(), 3);
});

check("the lead's prose is never cut at a bracket that only looks like a title", () => {
  const reply = roster.agents()[0].feed.find(entry => entry.kind === 'reply');
  assert.equal(reply.text, 'I will split this so nothing waits. [Scout] maps the colours.');
});

check('a read-only helper: role, brief from the spawn call, finished from its lifecycle text', () => {
  const scout = roster.agents()[1];
  assert.equal(scout.name, 'Scout');
  assert.equal(scout.role, 'read-only');
  assert.equal(scout.state, 'done');
  assert.equal(scout.action, 'Found 3 hard-coded colours: #fff and #1d2330 in styles.css.', 'a finished helper says what it found');
  assert.equal(scout.brief, 'Map where colours are set in `styles.css` and index.html.\nList each one.');
  assert.equal(scout.elapsedMs, 10000 - 1100);
  same(scout.files.map(file => [file.path, file.op]), [['index.html', 'read']],
    "a read's result is the file itself and is never searched for paths");
  const lines = scout.feed.map(entry => [entry.kind, entry.text, entry.ok]);
  same(lines[0], ['tool', 'read index.html', true]);
  same(lines[1], ['reply', 'Found 3 hard-coded colours.', true], 'streamed pieces join without the [Scout] prefix');
  assert.equal(lines[2][1], 'Found 3 hard-coded colours: #fff and #1d2330 in styles.css.');
  assert.ok(!lines.some(line => /Spawned|finished/.test(line[1])), 'lifecycle lines are state, not chat');
});

check('a builder: owned files as its role, counts from the fields or the tool message, claims held while it works', () => {
  const wirer = roster.agents()[2];
  assert.equal(wirer.state, 'working');
  assert.equal(wirer.action, 'Reading app.js');
  assert.equal(wirer.role, 'app.js, index.html');
  assert.match(wirer.brief, /^Add button#theme in the header/);
  const byPath = Object.fromEntries(wirer.files.map(file => [file.path, file]));
  assert.equal(byPath['app.js'].op, 'edit');
  assert.equal(byPath['index.html'].added, 9);
  assert.equal(byPath['index.html'].removed, 1);
  same(wirer.feed.map(entry => [entry.text, entry.ok]), [
    ['write app.js', true],
    ['patch index.html · +9 −1', true],
    ['read app.js', null],
  ]);
  same(roster.claims(), [
    { path: 'app.js', agentId: WIRER.agent_id, agentName: 'Wirer', state: 'held' },
    { path: 'index.html', agentId: WIRER.agent_id, agentName: 'Wirer', state: 'held' },
  ]);
});

check('an edit holds its file from the moment it starts, and a zero count is left out', () => {
  const side = ThomasCodeRoster.create();
  side.feed(child(WIRER, { kind: 'tool_started', name: 'Wirer > fs.write_file', text: '[Wirer] path: src/new.js', ts: at(1) }));
  same(side.claims(), [{ path: 'src/new.js', agentId: WIRER.agent_id, agentName: 'Wirer', state: 'held' }]);
  same(side.agents()[0].feed.map(entry => [entry.text, entry.ok]), [['write src/new.js', null]]);
  side.feed(child(WIRER, { kind: 'tool_result', name: 'Wirer > fs.write_file', text: '[Wirer] Wrote 812 chars to src/new.js', added: 31, removed: 0, ts: at(2) }));
  same(side.agents()[0].feed.map(entry => entry.text), ['write src/new.js · +31']);
  same(side.agents()[0].files, [{ path: 'src/new.js', added: 31, removed: 0, op: 'edit' }]);
});

check('the lead waiting on its helpers reads as coordinating its plan', () => {
  assert.equal(roster.agents()[0].action, 'Coordinating · step 2 of 3');
  assert.equal(roster.agents()[0].state, 'working');
  assert.equal(roster.working(), 2);
});

check('a repaint key that only moves when something visible does', () => {
  const before = roster.snapshotKey();
  clock += 5000;
  assert.equal(roster.snapshotKey(), before, 'a clock tick is not a change');
  roster.feed(child(WIRER, { kind: 'steering', text: 'make it a sun and moon icon', steer_id: 'steer-1', ts: at(21000) }));
  assert.notEqual(roster.snapshotKey(), before);
  assert.equal(roster.agents()[2].action, 'Reading your message');
});

check('pause holds everyone still working, and resume lets them go', () => {
  roster.feed({ type: 'output', kind: 'paused', text: 'Paused', ts: at(22000) });
  const held = roster.agents();
  same(held.map(agent => [agent.state, agent.action]), [
    ['waiting', 'Paused'], ['done', 'Found 3 hard-coded colours: #fff and #1d2330 in styles.css.'], ['waiting', 'Paused'],
  ]);
  roster.feed({ type: 'output', kind: 'resumed', text: 'Resumed', paused_ms: 4000, ts: at(26000) });
  assert.equal(roster.agents()[2].state, 'working');
});

check('parallel calls close in the order they finish, by name and path', () => {
  roster.feed(lead({ kind: 'tool_started', name: 'fs.read_file', text: 'path: a.js', path: 'a.js', ts: at(27000) }));
  roster.feed(lead({ kind: 'tool_started', name: 'fs.read_file', text: 'path: b.js', path: 'b.js', ts: at(27001) }));
  roster.feed(lead({ kind: 'tool_result', name: 'fs.read_file', text: 'contents of b', path: 'b.js', ts: at(27100) }));
  roster.feed(lead({ kind: 'tool_result', name: 'fs.read_file', text: 'no such file', path: 'a.js', is_error: true, ts: at(27200) }));
  const lines = roster.agents()[0].feed.slice(-2).map(entry => [entry.text, entry.ok]);
  same(lines, [['read a.js', false], ['read b.js', true]]);
});

check('a server-run helper follows its explicit agent_state', () => {
  roster.feed({ type: 'output', kind: 'agent_spawned', ...REVIEW, parent_agent_id: 'run-1', agent_state: 'starting', text: 'Reviewer started', ts: at(30000) });
  let reviewer = roster.agents().find(agent => agent.id === REVIEW.agent_id);
  same([reviewer.state, reviewer.action, reviewer.role], ['waiting', 'Waiting to start', 'helper']);
  roster.feed({ type: 'output', kind: 'agent_status', ...REVIEW, agent_mode: 'review', agent_state: 'running', model: 'gpt-5.6', text: 'Reviewer: running', ts: at(31000) });
  roster.feed({ type: 'output', kind: 'agent_event', ...REVIEW, agent_mode: 'review', model: 'gpt-5.6', text: 'Checked the toggle against both asks', is_error: false, ts: at(32000) });
  reviewer = roster.agents().find(agent => agent.id === REVIEW.agent_id);
  same([reviewer.state, reviewer.role, reviewer.action], ['working', 'review', 'Checked the toggle against both asks']);
  roster.feed({ type: 'output', kind: 'agent_status', ...REVIEW, agent_mode: 'review', agent_state: 'completed', text: 'Reviewer: completed', ts: at(33000) });
  reviewer = roster.agents().find(agent => agent.id === REVIEW.agent_id);
  assert.equal(reviewer.state, 'done');
});

check('a builder that finishes releases its files', () => {
  roster.feed(child(WIRER, { kind: 'tool_result', name: 'Wirer > fs.read_file', text: '[Wirer] const theme = 1;', path: 'app.js', ts: at(34000) }));
  roster.feed(child(WIRER, { kind: 'meta', text: '[Wirer] \nIntegrated index.html; lead must verify the combined project.', ts: at(35000) }));
  roster.feed(child(WIRER, { kind: 'meta', text: '[Wirer] Wirer finished', ts: at(36000) }));
  same(roster.claims().map(claim => claim.state), ['released', 'released']);
  assert.equal(roster.agents()[2].feed.at(-1).text, 'Integrated index.html; lead must verify the combined project.');
});

check('the Verifier is listed last and not counted as a crew member', () => {
  roster.setVerifier({ state: 'waiting', note: 'Waiting on Wirer' });
  const list = roster.agents();
  assert.equal(list.at(-1).id, 'verifier');
  same([list.at(-1).name, list.at(-1).role, list.at(-1).action], ['Verifier', 'separate evaluator', 'Waiting on Wirer']);
  assert.equal(roster.count(), 4);
});

check('who is listening comes from the run, per agent', () => {
  roster.setReachable(['lead', SCOUT.agent_id]);
  const list = roster.agents();
  same(list.map(agent => agent.reachable), [true, true, false, false, false]);
});

check("the lead's answer finishes it, and a stopped run stops whoever was left", () => {
  const side = ThomasCodeRoster.create();
  side.feed(lead({ kind: 'tool_started', name: 'shell.exec', text: 'command: npx vitest run', ts: at(40000) }));
  assert.equal(side.agents()[0].action, 'Running tests');
  side.feed(child(SCOUT, { kind: 'meta', text: '[Scout] Spawned Scout — read-only source review', ts: at(40100) }));
  side.feed(lead({ kind: 'final', text: 'Done. Your colours are variables now.', ts: at(41000) }));
  same(side.agents().map(agent => agent.state), ['done', 'working']);
  side.feed(lead({ kind: 'acceptance', ts: at(41100) }));
  assert.equal(side.agents()[0].state, 'done', 'the report written after an answer is not new work');
  side.feed({ type: 'stopped', text: 'Stopped' });
  same(side.agents().map(agent => agent.state), ['done', 'stopped']);
  side.reset();
  same(side.agents(), []);
});

check('a failed helper reads as failed, with the reason', () => {
  const side = ThomasCodeRoster.create();
  side.feed(child(WIRER, { kind: 'meta', text: '[Wirer] Spawned Wirer — isolated file builder', ts: at(50000) }));
  side.feed(child(WIRER, { kind: 'meta', text: '[Wirer] Wirer failed: parent refused integration: target changed', is_error: true, ts: at(51000) }));
  const wirer = side.agents()[0];
  assert.equal(wirer.state, 'failed');
  assert.equal(wirer.action, 'Failed: parent refused integration: target changed');
  assert.equal(wirer.feed.at(-1).ok, false);
});

// ---------- Drawer ----------
const agents = roster.agents();
agents[0].name = 'Thomas <lead>';
const drawer = ThomasCodeDrawer.html({
  esc, agents, claims: roster.claims(), expandedAgent: WIRER.agent_id, projectLabel: 'habit-tracker', running: true,
  changes: [{ file: 'styles.css', added: 12, removed: 3, untracked: false }, { file: 'notes/new.md', untracked: true }],
  extraHtml: '<details class="tc-code-files"><summary>Files</summary></details>',
});

check('the drawer head names the crew, not the Verifier or the project', () => {
  assert.match(drawer, /<strong>Activity<\/strong><small>4 agents<\/small>/);
  assert.doesNotMatch(drawer, /habit-tracker/, "the drawer head does not repeat the project or the task name");
  assert.match(drawer, /data-code-drawer-close/);
});

check('one card per agent, escaped, each one a toggle', () => {
  for (const agent of agents) assert.match(drawer, new RegExp(`data-code-agent="${agent.id}"`));
  assert.match(drawer, /Thomas &lt;lead&gt;/);
  assert.doesNotMatch(drawer, /Thomas <lead>/);
  assert.equal((drawer.match(/class="tb-box tb-md/g) || []).length, agents.length);
});

check('only the expanded agent shows its claims, feed and Open chat', () => {
  assert.equal((drawer.match(/data-code-agent-chat=/g) || []).length, 1);
  assert.match(drawer, new RegExp(`data-code-agent-chat="${WIRER.agent_id}">Open chat with Wirer<`));
  assert.match(drawer, new RegExp(`id="tc-agent-row-${WIRER.agent_id}" class="tc-agent-row" data-code-agent="${WIRER.agent_id}" aria-expanded="true" aria-controls="tc-agent-detail-${WIRER.agent_id}"`));
  assert.match(drawer, /id="tc-agent-row-lead" class="tc-agent-row" data-code-agent="lead" aria-expanded="false">/);
  assert.match(drawer, /<span class="tc-agent-chip" title="app.js">app.js<\/span>/);
  assert.match(drawer, /patch index.html · \+9 −1/);
});

check('claimed files and outputs keep the existing Keep and Revert hooks', () => {
  assert.match(drawer, /<div class="tc-agents-label">Claimed files<\/div>/);
  assert.match(drawer, /<span class="tc-agents-path" title="index.html">index.html<\/span><span>released<\/span>/);
  assert.match(drawer, /data-code-keep="styles.css"/);
  assert.match(drawer, /data-code-revert="styles.css"/);
  assert.match(drawer, /<span class="tc-agents-add">\+12<\/span><span class="tc-agents-del">−3<\/span>/);
  assert.match(drawer, /notes\/new.md<\/span><span class="tc-agents-new">new<\/span>/);
  assert.ok(drawer.trimEnd().endsWith('</details>\n      </div>\n    </div>'), 'the folded Files section comes last');
});

check('a waiting Verifier shows no made-up time, a finished helper its real one', () => {
  assert.match(drawer, /data-code-agent="verifier"[\s\S]*?<span class="tc-agent-time">—<\/span>/);
  assert.match(drawer, new RegExp(`data-code-agent="${SCOUT.agent_id}"[\\s\\S]*?<span class="tc-agent-time">8s</span>`));
  assert.equal(ThomasCodeDrawer.elapsedLabel(72000), '1m 12s');
  assert.equal(ThomasCodeDrawer.elapsedLabel(3_720_000), '1h 2m');
});

check('an empty roster says why it is empty', () => {
  const empty = ThomasCodeDrawer.html({ esc, agents: [], claims: [], changes: [], projectLabel: 'p', running: false });
  assert.match(empty, /No agents have worked on this task yet\./);
  assert.doesNotMatch(empty, /<small>/, 'with no agents the head says just Activity');
});

// A DOM just big enough for bind(): elements found by the attribute the
// selector names, holding their listeners.
function fakeElement(attrs = {}) {
  const listeners = {};
  return {
    dataset: { ...attrs }, classList: { contains: () => false, toggle() {} }, value: '', style: {},
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    fire(type, event = {}) { (listeners[type] || []).forEach(fn => fn({ preventDefault() { this.defaultPrevented = true; }, ...event })); },
    listeners,
  };
}

check('drawer clicks reach the handlers once, however often bind runs', () => {
  const toggle = fakeElement({ codeAgent: 'lead' });
  const open = fakeElement({ codeAgentChat: WIRER.agent_id });
  const close = fakeElement();
  const dom = { querySelectorAll: selector => ({ '[data-code-agent]': [toggle], '[data-code-agent-chat]': [open], '.tc-agents-drawer [data-code-drawer-close]': [close] }[selector] || []) };
  const calls = [];
  const handlers = { onToggleAgent: id => calls.push(['toggle', id]), onOpenChat: id => calls.push(['chat', id]), onClose: () => calls.push(['close']) };
  ThomasCodeDrawer.bind(dom, handlers);
  ThomasCodeDrawer.bind(dom, handlers);
  toggle.fire('click'); open.fire('click'); close.fire('click');
  same(calls, [['toggle', 'lead'], ['chat', WIRER.agent_id], ['close']]);
});

check('a run that failed shows its lead as failed, not stopped by you', () => {
  const side = ThomasCodeRoster.create();
  side.feed(lead({ kind: 'tool_started', name: 'fs.read_file', text: 'path: a.js', ts: at(60000) }));
  side.feed(child(SCOUT, { kind: 'meta', text: '[Scout] Spawned Scout — read-only source review', ts: at(60100) }));
  side.feed(lead({ kind: 'error', text: 'agent loop exited 1', ts: at(61000) }));
  side.feed({ type: 'output', kind: 'done', ok: false, ts: at(62000) });
  same(side.agents().map(agent => [agent.state, agent.action]), [['failed', 'Failed'], ['failed', 'Ended when the run failed']]);
  const stopped = ThomasCodeRoster.create();
  stopped.feed(lead({ kind: 'say', text: 'working', ts: at(1) }));
  stopped.feed({ type: 'output', kind: 'stopped' });
  same(stopped.agents().map(agent => [agent.state, agent.action]), [['stopped', 'Stopped']], 'a stop you asked for is still Stopped');
});

check('an answer streamed and then sent whole is one entry', () => {
  const side = ThomasCodeRoster.create();
  side.feed(lead({ kind: 'tool_result', name: 'diff.create', text: 'Replaced 1 line(s) with 2 line(s) in a.js', ts: at(1) }));
  side.feed(lead({ kind: 'say', text: 'I changed ', delta: true, ts: at(2) }));
  side.feed(lead({ kind: 'say', text: 'the header.', delta: true, ts: at(3) }));
  side.feed(lead({ kind: 'final', text: 'I changed the header.', ts: at(4) }));
  same(side.agents()[0].feed.map(entry => [entry.kind, entry.text]), [['tool', 'patch a.js · +2 −1'], ['reply', 'I changed the header.']]);
  side.feed(child(SCOUT, { kind: 'say', text: '\n[Scout] Found 3 colours.', delta: true, ts: at(5) }));
  side.feed(child(SCOUT, { kind: 'meta', text: '[Scout] Found 3 colours.', ts: at(6) }));
  same(side.agents()[1].feed.map(entry => entry.text), ['Found 3 colours.'], "a helper's answer, demoted to meta, is not a second reply");
  side.feed(lead({ kind: 'final', text: 'And the footer.', ts: at(7) }));
  assert.equal(side.agents()[0].feed.filter(entry => entry.kind === 'reply').length, 2, 'a different answer is its own entry');
});

check('the drawer lists the helpers still at it first, and folds many finished ones', () => {
  const crew = [
    { id: 'lead', name: 'Thomas', role: 'lead', state: 'working', files: [], feed: [] },
    ...Array.from({ length: 5 }, (_v, i) => ({ id: `done${i}`, name: `Old ${i}`, role: 'builder', state: i === 4 ? 'failed' : 'done', files: [], feed: [], elapsedMs: 9000 })),
    { id: 'live1', name: 'Wirer', role: 'builder', state: 'working', files: [], feed: [] },
    { id: 'verifier', name: 'Verifier', role: 'separate evaluator', state: 'waiting', files: [], feed: [] },
  ];
  const ids = html => [...html.matchAll(/data-code-agent="([^"]+)"/g)].map(match => match[1]);
  const folded = ThomasCodeDrawer.html({ esc, agents: crew, claims: [], changes: [], running: true });
  same(ids(folded), ['lead', 'live1', 'verifier'], 'the lead, the helper still working, then the Verifier');
  assert.match(folded, /<button type="button" class="tc-agents-earlier" data-code-agents-earlier aria-expanded="false">5 earlier helpers<\/button>/);
  const open = ThomasCodeDrawer.html({ esc, agents: crew, claims: [], changes: [], running: true, earlierOpen: true });
  same(ids(open), ['lead', 'live1', 'done0', 'done1', 'done2', 'done3', 'done4', 'verifier']);
  assert.match(open, /aria-expanded="true">5 earlier helpers</);
  const expanded = ThomasCodeDrawer.html({ esc, agents: crew, claims: [], changes: [], running: true, expandedAgent: 'done2' });
  assert.ok(ids(expanded).includes('done2'), 'expanding a finished helper opens the fold it sits in');
  const few = ThomasCodeDrawer.html({ esc, agents: crew.filter(agent => !['done3', 'done4'].includes(agent.id)), claims: [], changes: [], running: true });
  same(ids(few), ['lead', 'live1', 'done0', 'done1', 'done2', 'verifier'], 'three finished helpers stay listed, after the live ones');
  assert.doesNotMatch(few, /data-code-agents-earlier/);
  const toggle = fakeElement();
  const dom = { querySelectorAll: selector => (selector === '[data-code-agents-earlier]' ? [toggle] : []) };
  let toggled = 0;
  ThomasCodeDrawer.bind(dom, { onToggleEarlier: () => { toggled += 1; } });
  ThomasCodeDrawer.bind(dom, { onToggleEarlier: () => { toggled += 1; } });
  toggle.fire('click');
  assert.equal(toggled, 1);
});

// ---------- Agent side chat ----------
const wirer = roster.agents()[2];
const receipts = [
  { id: 'm2', agent_id: WIRER.agent_id, text: 'also keep it top right', state: 'queued', queued_at: T0 + 37000, acked_at: null },
  { id: 'm1', agent_id: WIRER.agent_id, text: 'make it a `sun` icon', state: 'acked', queued_at: T0 + 20500, acked_at: T0 + 21000 },
  { id: 'm0', agent_id: 'lead', text: 'not for Wirer', state: 'queued', queued_at: T0 + 100 },
];
const thread = ThomasCodeAgentChat.threadFor(wirer, receipts);

check('the thread is the brief, then everything in the order it happened', () => {
  same(thread[0], { who: 'thomas', kind: 'brief', text: wirer.brief, ts: wirer.startedAt });
  const mine = thread.filter(item => item.who === 'you');
  same(mine.map(item => [item.text, item.state]), [['make it a `sun` icon', 'acked'], ['also keep it top right', 'queued']]);
  const order = thread.map(item => item.ts);
  same(order.slice(1), [...order.slice(1)].sort((a, b) => a - b));
  assert.ok(thread.some(item => item.who === 'agent' && item.kind === 'tool' && item.text === 'patch index.html · +9 −1' && item.ok === true));
  assert.ok(thread.some(item => item.who === 'agent' && item.kind === 'reply'));
});

const open = ThomasCodeAgentChat.html({ esc, agent: { ...wirer, state: 'working', reachable: true }, thread, draft: 'and <b>bold</b>', sending: false, error: '' });
check('the panel: header, brief label, grouped lines, your messages with their badge, a composer', () => {
  assert.match(open, /^<aside class="tc-code-agent-chat is-entering" data-agent-chat-for="child_a1b2c3d4e5f6"/);
  assert.match(open, /<strong>Thomas ↔ Wirer<\/strong><small>app.js, index.html · direct control<\/small>/);
  assert.match(open, /data-agent-chat-close/);
  assert.match(open, /THOMAS → WIRER · BRIEF/);
  assert.match(open, /<div class="tc-agent-chat-label">WIRER<\/div>/);
  assert.match(open, /<span class="tc-agent-chat-mark is-ok" aria-hidden="true">✓<\/span> patch index.html · \+9 −1/);
  assert.match(open, /YOU → WIRER/);
  assert.match(open, /make it a <code>sun<\/code> icon/);
  assert.match(open, /data-state="acked">acked</);
  assert.match(open, /data-state="queued">queued</);
  assert.match(open, /<textarea id="tc-agent-chat-input" data-agent-chat-input rows="1" placeholder="Message Wirer…" aria-label="Message Wirer">and &lt;b&gt;bold&lt;\/b&gt;<\/textarea>/);
  assert.match(open, /data-agent-chat-send/);
  assert.doesNotMatch(open, /<b>bold<\/b>/);
});

check('an agent that cannot be reached gets the reason instead of a composer', () => {
  const done = ThomasCodeAgentChat.html({ esc, agent: { ...wirer, state: 'done', reachable: false }, thread });
  assert.doesNotMatch(done, /data-agent-chat-input/);
  assert.match(done, /Wirer has finished, so it can&#39;t take messages any more\./);
  const leadPanel = ThomasCodeAgentChat.html({ esc, agent: { ...roster.agents()[0], state: 'working', reachable: false, brief: '' }, thread: [] });
  assert.match(leadPanel, /You ↔ Thomas/);
  assert.match(leadPanel, /Thomas can&#39;t take direct messages on this run\. Steer it from the main composer\./);
  const server = ThomasCodeAgentChat.html({ esc, agent: { id: REVIEW.agent_id, name: 'Reviewer', role: 'review', state: 'working', reachable: false, feed: [] }, thread: [] });
  assert.match(server, /Reviewer runs inside Thomas&#39;s server/);
  assert.match(server, /Nothing from Reviewer yet\./);
});

check('a send in flight and an error both show', () => {
  const busy = ThomasCodeAgentChat.html({ esc, agent: { ...wirer, reachable: true }, thread, draft: 'x', sending: true, error: 'Wirer has stopped listening.' });
  assert.match(busy, /data-agent-chat-form data-sending="1"/);
  assert.match(busy, /disabled aria-busy="true"/);
  assert.match(busy, /role="alert">Wirer has stopped listening\.</);
});

check('Enter sends, Shift+Enter does not, Escape and the close button close', () => {
  const input = fakeElement();
  const form = fakeElement();
  const send = fakeElement();
  const closeButton = fakeElement();
  const thread = { ...fakeElement(), scrollHeight: 500, clientHeight: 200, scrollTop: 0 };
  input.focus = () => {};
  input.setSelectionRange = () => {};
  const panel = fakeElement({ agentChatFor: WIRER.agent_id });
  panel.classList = { contains: name => name === 'is-entering', toggle() {} };
  panel.matches = selector => selector === '.tc-code-agent-chat';
  panel.querySelector = selector => ({
    '[data-agent-chat-close]': closeButton, '[data-agent-chat-thread]': thread, '[data-agent-chat-form]': form,
    '[data-agent-chat-input]': input, '[data-agent-chat-send]': send,
  }[selector] || null);
  const calls = [];
  ThomasCodeAgentChat.bind(panel, { onSend: text => calls.push(['send', text]), onClose: () => calls.push(['close']), onDraft: text => calls.push(['draft', text]) });
  assert.equal(thread.scrollTop, 300, 'opens at the newest message');
  input.value = '  keep it top right  ';
  input.fire('input');
  input.fire('keydown', { key: 'Enter', shiftKey: true });
  input.fire('keydown', { key: 'Enter', shiftKey: false });
  form.dataset.sending = '1';
  input.fire('keydown', { key: 'Enter' });
  closeButton.fire('click');
  panel.fire('keydown', { key: 'Escape' });
  same(calls, [['draft', '  keep it top right  '], ['send', 'keep it top right'], ['close'], ['close']]);
});

check('a repaint while you type puts the caret back where it was', () => {
  const makePanel = (entering, value) => {
    const input = { ...fakeElement(), value, selection: null, focused: false };
    input.setSelectionRange = (start, end) => { input.selection = [start, end]; input.selectionStart = start; input.selectionEnd = end; };
    input.focus = () => { input.focused = true; };
    const form = fakeElement();
    const panel = fakeElement({ agentChatFor: 'lead' });
    panel.classList = { contains: name => entering && name === 'is-entering', toggle() {} };
    panel.matches = selector => selector === '.tc-code-agent-chat';
    panel.querySelector = selector => ({ '[data-agent-chat-form]': form, '[data-agent-chat-input]': input }[selector] || null);
    return { panel, input };
  };
  const first = makePanel(true, 'fix the header');
  ThomasCodeAgentChat.bind(first.panel, {});
  same([first.input.selection, first.input.focused], [[14, 14], true], 'a panel that slides in puts you at the end of the draft');
  first.input.selectionStart = 4; first.input.selectionEnd = 4;
  first.input.fire('keyup');
  const second = makePanel(false, 'fix the header');
  ThomasCodeAgentChat.bind(second.panel, {});
  same([second.input.selection, second.input.focused], [[4, 4], false], 'a repaint restores the caret and leaves focus to the surface');
});

context.Date.now = realNow;
console.log(JSON.stringify({ ok: true, checks }));
