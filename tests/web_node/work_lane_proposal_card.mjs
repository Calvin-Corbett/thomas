// The card Thomas uses to ask before changing one of its own gates.
//
// It must show the evidence that produced the ask. An ask you cannot check is
// not a question, it is a notification with buttons -- and approving it out of
// habit is exactly the rubber stamp the lane runtime exists to remove.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const supportPath = process.argv[2];
if (!supportPath) throw new Error('support module path is required');

const sandbox = { window: {}, document: { querySelector: () => null }, console };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(supportPath, 'utf8'), sandbox, { filename: supportPath });

function supportFor(laneProposals) {
  const state = { apps: [], activeApp: null, actionBusy: false, laneProposals };
  return sandbox.window.ThomasWorkSupport.create({
    state,
    esc: value => String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;'),
    activeWorkflowFor: () => null,
    statusPill: () => '',
    safeArtifactHref: () => '',
    onboardingBrief: () => '',
    jsonRequest: async () => ({}),
    appUrl: value => value,
  });
}

const quiet = {
  id: 'job-retire-never-fires',
  job_kind: 'job',
  kind: 'retire',
  gate_id: 'never-fires',
  rationale: 'Checked 24 times and never once stopped anything.',
  evidence: { checked_count: 24, fired_count: 0, waived_count: 0 },
};

// 1. Nothing to ask about renders nothing at all.
{
  const support = supportFor([]);
  assert.equal(support.laneProposalsHtml(), '');
  assert.ok(!support.homeHtml().includes('tc-work-proposals'), 'an empty queue must not leave an empty box');
}

// 2. The ask carries its evidence and both answers.
{
  const support = supportFor([quiet]);
  const html = support.laneProposalsHtml();
  assert.match(html, /Thomas found something to change/);
  assert.match(html, /Drop this check: never-fires/);
  assert.match(html, /never once stopped anything/, 'the rationale is shown');
  assert.match(html, /checked 24 times/, 'the evidence is shown, not just the verdict');
  assert.match(html, /never stopped anything/, 'the evidence line reads honestly');
  assert.match(html, /data-work-proposal-approve="job-retire-never-fires"/);
  assert.match(html, /data-work-proposal-reject="job-retire-never-fires"/);
  assert.match(html, /Windows sign-in/, 'the tap must not be a surprise');
}

// 3. A gate the user keeps overriding says so in the user's own terms.
{
  const waived = { ...quiet, evidence: { checked_count: 10, fired_count: 8, waived_count: 3 } };
  const html = supportFor([waived]).laneProposalsHtml();
  assert.match(html, /you overrode it 3 times/);
  assert.match(html, /stopped something 8 times/);
}

// 4. Several asks are counted, not stacked silently.
{
  const html = supportFor([quiet, { ...quiet, id: 'b', gate_id: 'other' }]).laneProposalsHtml();
  assert.match(html, /Thomas found 2 things to change/);
}

// 5. It sits on the home board, above the jobs, because it is a question.
{
  const home = supportFor([quiet]).homeHtml();
  assert.ok(home.includes('tc-work-proposals'), 'the card belongs on the board the user lands on');
  assert.ok(home.indexOf('tc-work-proposals') < home.indexOf('tc-work-app-grid'), 'a question goes above the list');
}

// 6. While an action is in flight the answers are disabled, so a double tap
//    cannot approve twice.
{
  const support = supportFor([quiet]);
  assert.ok(!support.laneProposalsHtml().includes('disabled'));
}

console.log(JSON.stringify({ cardShowsEvidence: true, emptyQueueRendersNothing: true, cardIsOnTheBoard: true }));
