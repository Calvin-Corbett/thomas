// The step rail: where the job actually is.
//
// The row it replaces was `phaseIndex >= 0` where phaseIndex was
// `Math.max(0, ...)` -- always true, so step one read as done before any goal
// existed, and steps two and three lit from the model's own phase claim. The
// rail is server-computed from the ledger the gates run on, so what the user
// sees and what actually blocks cannot disagree.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const supportPath = process.argv[2];
if (!supportPath) throw new Error('support module path is required');

const sandbox = { window: {}, document: { querySelector: () => null }, console };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(supportPath, 'utf8'), sandbox, { filename: supportPath });

function supportFor(laneRail, extra = {}) {
  return sandbox.window.ThomasWorkSupport.create({
    state: { apps: [], activeApp: null, actionBusy: false, laneRail, laneProposals: [], ...extra },
    esc: value => String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;'),
    activeWorkflowFor: () => null,
    statusPill: () => '',
    safeArtifactHref: () => '',
    onboardingBrief: () => '',
    jsonRequest: async () => ({}),
    appUrl: value => value,
  });
}

const fresh = [
  { id: 'goal_discovery', name: 'Discover the goal', state: 'open', unmet: ['goal-substantive: confirmed_goal is 0 chars, needs at least 12'] },
  { id: 'workflow_mapping', name: 'Map the workflows', state: 'locked', unmet: [] },
  { id: 'workflow_configuration', name: 'Configure the chosen workflow', state: 'locked', unmet: [] },
];

// 1. A fresh wizard must NOT show step one as done. This is the whole bug.
{
  const html = supportFor(fresh).stepRailHtml(fresh);
  assert.ok(!html.includes('is-passed'), 'nothing is done on a fresh wizard');
  assert.match(html, /is-open/);
  assert.match(html, /1 · Discover the goal/);
  assert.match(html, /in progress/);
  assert.match(html, /not started/);
  assert.match(html, /needs at least 12/, 'the open step says what it is waiting for');
}

// 2. Progress is real progress.
{
  const moved = [
    { ...fresh[0], state: 'passed', unmet: [] },
    { ...fresh[1], state: 'open', unmet: ['workflows-mapped: workflows has 0 entries, needs 1..6'] },
    fresh[2],
  ];
  const html = supportFor(moved).stepRailHtml(moved);
  assert.match(html, /is-passed/);
  assert.ok(html.indexOf('is-passed') < html.indexOf('is-open'), 'done steps come before the open one');
  assert.match(html, /needs 1\.\.6/);
}

// 3. A waived step is the loudest thing on the rail. Momentum is not amnesia.
{
  const waived = [{ ...fresh[0], state: 'waived', unmet: [] }, fresh[1], fresh[2]];
  const html = supportFor(waived).stepRailHtml(waived);
  assert.match(html, /is-waived/);
  assert.match(html, /skipped, not verified/);
  assert.match(html, /1 step skipped without being verified/);
}

{
  const two = [{ ...fresh[0], state: 'waived' }, { ...fresh[1], state: 'waived' }, fresh[2]];
  assert.match(supportFor(two).stepRailHtml(two), /2 steps skipped without being verified/);
}

// 4. A blocked step is visibly different from one merely waiting.
{
  const blocked = [{ ...fresh[0], state: 'blocked', unmet: ['goal-substantive: confirmed_goal is 0 chars'] }, fresh[1], fresh[2]];
  const html = supportFor(blocked).stepRailHtml(blocked);
  assert.match(html, /is-blocked/);
  assert.match(html, />blocked</);
  assert.ok(!html.includes('skipped without being verified'), 'blocked is not skipped');
}

// 5. No rail yet renders nothing rather than an empty or fake one.
{
  assert.equal(supportFor([]).stepRailHtml([]), '');
  assert.equal(supportFor(undefined).stepRailHtml(undefined), '');
}

// 6. The always-true progress markup is gone from the module entirely.
{
  const source = fs.readFileSync(supportPath, 'utf8');
  assert.ok(!source.includes('tc-work-progress'), 'the always-lit progress bar must be gone');
  // Comment lines are excluded on purpose: the replacement documents the bug it
  // replaced by quoting it, and that quote must not read as the bug surviving.
  const live = source.split(/\r?\n/).filter(line => !line.trim().startsWith('//')).join(' ');
  assert.ok(!/const phaseIndex = Math\.max/.test(live), 'and so must the computation behind it');
  assert.ok(!/phaseIndex >= 0/.test(live), 'the always-true test must not survive in live code');
}

// 7. A waiting step speaks to the person, never in the checker's own names
// (2026-11-09). The rail printed "selection-is-the-users: selected_workflow_id
// is empty" as it came, and went on printing it after a workflow was chosen,
// because the rail only refreshes on Thomas's next turn.
{
  const waiting = [
    { ...fresh[0], state: 'passed', unmet: [] },
    { ...fresh[1], state: 'passed', unmet: [] },
    { ...fresh[2], state: 'open', unmet: ['selection-is-the-users: selected_workflow_id is empty'] },
  ];
  const before = supportFor(waiting).stepRailHtml(waiting);
  assert.match(before, /Choose one of the workflows below\./);
  assert.ok(!before.includes('selection-is-the-users'), 'the check id stays off the screen');
  assert.ok(!before.includes('selected_workflow_id'), 'and so does the field name');
  const after = supportFor(waiting, { onboardingWorkflowId: 'wf-1' }).stepRailHtml(waiting);
  assert.ok(!after.includes('tc-work-rail-why'), 'once a workflow is chosen the step stops asking for one');
  const goal = supportFor(fresh).stepRailHtml(fresh);
  assert.ok(!goal.includes('goal-substantive') && !goal.includes('confirmed_goal'), 'the goal step is in plain words too');
  const other = [{ ...fresh[0], unmet: ['some-new-check: next_step is missing'] }, fresh[1], fresh[2]];
  const html = supportFor(other).stepRailHtml(other);
  assert.ok(html.includes('next step is missing') && !html.includes('some-new-check'), 'an unknown reason loses its id and its underscores');
}

// 8. With no jobs, the page says what a job is and where to type one.
{
  const empty = supportFor([]).homeHtml();
  assert.match(empty, /No jobs yet/);
  assert.match(empty, /Describe yours in the box below/);
  assert.ok(!/Mission-backed|connector identities/.test(empty), 'no internal vocabulary in the page heading');
}

console.log(JSON.stringify({ freshWizardShowsNothingDone: true, waiverIsLoud: true, blockedIsDistinct: true, reasonsArePlain: true, emptyPageExplains: true }));
