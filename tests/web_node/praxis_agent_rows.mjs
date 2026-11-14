import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const window = {};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), { window });
const escapeHtml = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
const row = window.ThomasCodeAgentRows.render({
  kind: 'agent_status', agent_id: 'child-1', agent_title: '<review>',
  agent_mode: 'review', model: 'gpt-5.6-luna', agent_state: 'running', text: 'Reading source',
}, escapeHtml, true);
assert.match(row, /data-agent-id="child-1"/);
assert.match(row, /&lt;review>/);
assert.match(row, /gpt-5\.6-luna · running · Reading source/);
assert.match(row, /data-saved="true"/);
assert.equal(window.ThomasCodeAgentRows.render({ kind: 'planning', agent_id: 'child-1' }, escapeHtml, false), '');
assert.doesNotMatch(row, /<review>/);
const retrying = window.ThomasCodeAgentRows.render({
  kind: 'agent_status', agent_id: 'child-1', agent_title: 'Review',
  agent_mode: 'review', model: 'gpt-5.6-luna', agent_state: 'retrying', text: 'Retry after provider limit',
}, escapeHtml, false);
assert.match(retrying, /gpt-5\.6-luna · retrying · Retry after provider limit/);
const resuming = window.ThomasCodeAgentRows.render({
  kind: 'agent_status', agent_id: 'child-1', agent_title: 'Review',
  agent_mode: 'review', model: 'gpt-5.6-luna', agent_state: 'quota_wait', text: 'Review: resuming',
}, escapeHtml, false);
assert.match(resuming, /gpt-5\.6-luna · resuming · Review: resuming/);
console.log('Praxis agent rows keep live and saved identity');
