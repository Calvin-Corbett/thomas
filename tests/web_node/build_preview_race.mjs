import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const filename = process.argv[2];
if (!filename) throw new Error('usage: node build_preview_race.mjs <unified_code_results.js>');
const pending = [];
const state = { activeId: 'build-1', filePreview: null, tree: [], treePath: '', treeLoaded: false };
let renders = 0;
const context = {
  window: { ThomasCodeArtifacts: { create: () => ({}) } },
  fetch(url) {
    return new Promise(resolve => pending.push({ url, resolve }));
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(filename, 'utf8'), context, { filename });
context.window.ThomasCodeResults.configure({
  state,
  esc: s => s,
  isInternalResultPath: () => false,
  lifecycle: () => ({
    contextToken: current => ({ id: current.activeId }),
    contextMatches: (current, token) => current.activeId === token.id,
  }),
  render: () => { renders++; },
  pushLiveEvent: () => { throw new Error('unexpected preview error'); },
});
const resolveFile = (index, path, content) => {
  assert.match(pending[index].url, new RegExp(encodeURIComponent(path).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  pending[index].resolve({ ok: true, json: async () => ({ ok: true, path, content }) });
};
const older = context.window.ThomasCodeResults.loadFile('old.txt');
const newer = context.window.ThomasCodeResults.loadFile('new.txt');
resolveFile(1, 'new.txt', 'new');
assert.equal(await newer, true);
resolveFile(0, 'old.txt', 'old');
assert.equal(await older, false);
assert.equal(state.filePreview.path, 'new.txt', 'late response must not replace the latest selection');
assert.equal(renders, 1);

const same = context.window.ThomasCodeResults.loadFile('new.txt');
resolveFile(2, 'new.txt', 'new');
assert.equal(await same, true);
assert.equal(renders, 1, 'an unchanged refresh must not destroy the preview iframe');

const changed = context.window.ThomasCodeResults.loadFile('new.txt');
resolveFile(3, 'new.txt', 'updated');
assert.equal(await changed, true);
assert.equal(state.filePreview.content, 'updated');
assert.equal(renders, 2);
const closing = context.window.ThomasCodeResults.loadFile('closed.txt');
context.window.ThomasCodeResults.invalidateFileRequest();
state.filePreview = null;
resolveFile(4, 'closed.txt', 'closed');
assert.equal(await closing, false);
assert.equal(state.filePreview, null, 'closing the viewer must not reopen a pending file');
const olderTree = context.window.ThomasCodeResults.loadTree('old');
const newerTree = context.window.ThomasCodeResults.loadTree('new');
pending[6].resolve({ ok: true, json: async () => ({ ok: true, path: 'new', entries: [{ name: 'new.txt' }] }) });
assert.equal(await newerTree, true);
pending[5].resolve({ ok: true, json: async () => ({ ok: true, path: 'old', entries: [{ name: 'old.txt' }] }) });
assert.equal(await olderTree, false);
assert.equal(state.treePath, 'new', 'late folder response must not replace the current folder');
assert.equal(state.tree[0].name, 'new.txt');
assert.equal(renders, 3, 'stale folder response must not re-render the drawer');
process.stdout.write('Build preview and folder response races: passed\n');
