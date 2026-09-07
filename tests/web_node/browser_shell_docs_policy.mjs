// Runs browser_shell_docs_policy.js in a vm context and reports what its
// decisions actually are, so the Python test asserts behaviour, not source.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const modulePath = process.argv[2];
const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(readFileSync(modulePath, 'utf8'), sandbox, { filename: 'browser_shell_docs_policy.js' });
const policy = sandbox.window.ThomasBrowserDocsPolicy;
if (!policy) { process.stderr.write('window.ThomasBrowserDocsPolicy missing\n'); process.exit(1); }

const home = { id: 1, kind: 'chat-home', mode: 'chat', chatId: 'a', activatedAt: 5 };
const docB = { id: 2, kind: 'doc', mode: 'chat', chatId: 'b', activatedAt: 7 };
const build1 = { id: 3, kind: 'doc', mode: 'code', chatId: '', activatedAt: 2 };
const build2 = { id: 4, kind: 'doc', mode: 'code', chatId: '', activatedAt: 9 };
const tabs = [home, docB, build1, build2];
const blank = { mode: 'chat', chatId: '', busy: false, draft: '', hasContent: false };
const drafted = Object.assign({}, blank, { draft: 'half a thought' });
const busy = Object.assign({}, blank, { busy: true });
const rowA = { id: 'a', mode: 'chat', title: 'Alpha' };
const rowB = { id: 'b', mode: 'chat', title: 'Beta' };
const rowZ = { id: 'z', mode: 'chat', title: 'Zeta' };
const decide = (surface, row, modifiers) => policy.decideRowClick({ surface, row, tabs, modifiers: modifiers || {} });
const report = {
  row_held_by_home: decide(blank, rowA).action + ':' + (decide(blank, rowA).tab || {}).id,
  row_held_by_doc: decide(blank, rowB).action + ':' + (decide(blank, rowB).tab || {}).id,
  row_on_blank_surface: decide(blank, rowZ).action,
  row_on_blank_with_ctrl: decide(blank, rowZ, { ctrl: true }).action,
  row_on_blank_with_middle: decide(blank, rowZ, { middle: true }).action,
  row_on_drafted_surface: decide(drafted, rowZ).action,
  row_on_busy_surface: decide(busy, rowZ).action,
  row_on_other_mode_surface: decide(Object.assign({}, blank, { mode: 'code' }), rowZ).action,
  mode_click_home_mode: policy.decideModeClick({ mode: 'chat', home, tabs }).tab.id,
  mode_click_newest_doc: policy.decideModeClick({ mode: 'code', home, tabs }).tab.id,
  mode_click_no_doc: policy.decideModeClick({ mode: 'work', home, tabs }).action,
  new_chat_on_blank: policy.decideNewChat({ surface: blank }).action,
  new_chat_on_drafted: policy.decideNewChat({ surface: drafted }).action,
  new_chat_on_busy_keeps_mode: policy.decideNewChat({ surface: Object.assign({}, busy, { mode: 'code' }) }).mode,
  url_chat: policy.docUrlFor({ mode: 'chat', chatId: 'a b' }),
  url_code: policy.docUrlFor({ mode: 'code', chatId: 'c/1' }),
  url_work: policy.docUrlFor({ mode: 'work' }),
  blank_idle_with_content: policy.blankIdle(Object.assign({}, blank, { hasContent: true })),
  blank_idle_when_holding: policy.blankIdle(Object.assign({}, blank, { chatId: 'a' })),
  row_on_holding_surface: decide(Object.assign({}, blank, { chatId: 'q' }), rowZ).action,
};
process.stdout.write(JSON.stringify(report));
