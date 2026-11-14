// Readiness must not be the model's own claim wearing a checker's name.
//
// Until 2026-09-08 `onboardingConfigurationReady` returned
//   state.structuredOnboardingState.selected_workflow_configured === true
// and `advanceOnboardingPhase` wrote that result straight back into
// `selected_workflow_configured`. The function read as the browser verifying the
// model's claim about its own work; it re-read the claim. The Finish button was
// unlocked by the assertion that it should be unlocked.
//
// Readiness is now two independent facts: the MODEL's semantic judgement that the
// workflow is configured, and the BROWSER's record of the turn at which the USER
// chose. Neither stands in for the other.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const supportPath = process.argv[2];
if (!supportPath) throw new Error('support module path is required');

const sandbox = { window: {}, document: { querySelector: () => null }, console };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(supportPath, 'utf8'), sandbox, { filename: supportPath });

const workflow = {
  id: 'dinner-party-plan',
  name: 'Dinner party plan',
  purpose: 'Menu, shopping list, and timeline for six.',
  type: 'manual',
  connector_suggestions: [],
};

function supportFor({ selectionTurn, modelSaysConfigured }) {
  const state = {
    running: false,
    stage: 'onboarding',
    activeApp: { id: 'app-1', name: 'Dinner' },
    onboardingPhase: 'workflow_configuration',
    onboardingWorkflowId: workflow.id,
    onboardingSelectionUserTurn: selectionTurn,
    sessionId: 'session-1',
    messages: [{ role: 'user', text: 'Plan a dinner party.' }, { role: 'user', text: 'Use Dinner party plan.' }],
    structuredOnboardingState: {
      phase: 'workflow_configuration',
      confirmed_goal: 'Plan a dinner party for six on Saturday',
      selected_workflow_id: workflow.id,
      selected_workflow_configured: modelSaysConfigured,
      workflows: [workflow],
    },
  };
  const support = sandbox.window.ThomasWorkSupport.create({
    state,
    esc: value => String(value == null ? '' : value),
    activeWorkflowFor: () => null,
    statusPill: () => '',
    safeArtifactHref: () => '',
    onboardingBrief: () => '',
    jsonRequest: async () => ({}),
    appUrl: value => value,
  });
  return { state, support };
}

// 1. The circular case. The model asserts it is configured and nothing records a
//    user ever choosing. Before the fix this was "ready".
{
  const { support } = supportFor({ selectionTurn: 0, modelSaysConfigured: true });
  assert.equal(
    support.onboardingConfigurationReady(support.onboardingWorkflowCandidates()),
    false,
    'a model claim with no recorded user selection must not be readiness',
  );
  assert.match(
    support.onboardingFinishReason(),
    /Choose the workflow again/,
    'the refusal must be distinguishable and recoverable, not the generic configure message',
  );
}

// 2. Both halves present.
{
  const { support } = supportFor({ selectionTurn: 2, modelSaysConfigured: true });
  assert.equal(support.onboardingConfigurationReady(support.onboardingWorkflowCandidates()), true);
  assert.equal(support.onboardingFinishReason(), '', 'a real selection plus a model judgement is ready');
}

// 3. The user really chose, but the model has not judged it configured. The model
//    still owns that call -- this is not replaced by a browser heuristic.
{
  const { support } = supportFor({ selectionTurn: 2, modelSaysConfigured: false });
  assert.equal(support.onboardingConfigurationReady(support.onboardingWorkflowCandidates()), false);
  assert.match(support.onboardingFinishReason(), /Finish configuring/);
}

// 4. The two facts are independent: neither reads the other.
{
  const claimOnly = supportFor({ selectionTurn: 0, modelSaysConfigured: true }).support;
  assert.equal(claimOnly.modelReportedConfigured(), true);
  assert.equal(claimOnly.selectionCameFromTheUser(), false);

  const turnOnly = supportFor({ selectionTurn: 3, modelSaysConfigured: false }).support;
  assert.equal(turnOnly.modelReportedConfigured(), false);
  assert.equal(turnOnly.selectionCameFromTheUser(), true);
}

// 5. A restore that carries no stored turn must not erase a click this browser
//    already recorded for the same selection.
{
  const { state, support } = supportFor({ selectionTurn: 2, modelSaysConfigured: true });
  support.restoreOnboardingWorkflow({
    workflow_drafts: [workflow],
    selected_workflow_id: workflow.id,
    confirmed_goal: 'Plan a dinner party for six on Saturday',
    selected_workflow_configured: true,
  });
  assert.equal(state.onboardingSelectionUserTurn, 2, 'a recorded click survived a restore that stored none');
}

// 6. A restore onto a DIFFERENT selection must not inherit the old turn.
{
  const { state, support } = supportFor({ selectionTurn: 2, modelSaysConfigured: true });
  const other = { ...workflow, id: 'other-plan', name: 'Other plan' };
  support.restoreOnboardingWorkflow({
    workflow_drafts: [other],
    selected_workflow_id: other.id,
    confirmed_goal: 'Plan a dinner party for six on Saturday',
    selected_workflow_configured: true,
  });
  assert.equal(state.onboardingSelectionUserTurn, 0, 'a different selection must record its own turn');
}

console.log(JSON.stringify({ readinessIsNotCircular: true, factsAreIndependent: true, restoreKeepsTheClick: true }));
