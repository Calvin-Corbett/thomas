// A revisited chat must get its task activity card back — running AND settled.
//
// Measured 2026-08-05 (w2-work-mode, chat-side): a dispatched task's
// "On it — working on this" card (STEP BY STEP / JUMP IN) existed only in the
// live render. On every revisit the transcript showed just the status
// sentence: chat.html restored a card ONLY for verified completions with
// artifacts (restoreVerifiedChatArtifacts) or rows its inline isTerminal list
// called non-terminal. That list was also out of step with the server
// (thomas/server/chat_delegation_session.py counts 'verified' and 'abandoned'
// as terminal), so a failed/abandoned task's revisit had NO card at all and a
// 'verified' row would have been restored as running forever.
//
// This harness drives the real classification/merge helpers from
// js/chat_turn_flow.js in a vm, plus the chat.html wiring that uses them.
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
const modulePath = process.argv[3];
if (!htmlPath || !modulePath) throw new Error('usage: node chat_task_card_revisit_restore.mjs <chat.html> <chat_turn_flow.js>');
const html = fs.readFileSync(htmlPath, 'utf8');
const moduleSource = fs.readFileSync(modulePath, 'utf8');

const context = { window: {}, document: { createElement: () => ({}) }, console };
vm.createContext(context);
vm.runInContext(moduleSource, context);
const flow = context.window.ThomasChatTurnFlow;

const checks = {};
checks.moduleExportsRestoreHelpers = Boolean(flow)
  && typeof flow.planDelegationRestore === 'function'
  && typeof flow.mergeRestoredSteps === 'function'
  && typeof flow.delegationStepStatus === 'function';

// ---- classification: aligned with the server's terminal vocabulary ----
const status = (state) => flow.delegationStepStatus({ state });
checks.runningStaysRunning = status('running') === 'running' && status('requested') === 'running' && status('in_progress') === 'running';
checks.failureShapesAreFailed = status('failed') === 'failed' && status('error') === 'failed' && status('blocked') === 'failed' && status('abandoned') === 'failed';
checks.cancelledIsCancelled = status('cancelled') === 'cancelled' && status('canceled') === 'cancelled';
// 'verified' is the server's own terminal state — the old inline list missed
// it, which would restore a verified task as running (spinner forever).
checks.verifiedIsTerminalCompleted = status('verified') === 'completed' && status('completed') === 'completed' && status('done') === 'completed';

// ---- planning: which rows land on the card, and where it attaches ----
const rows = [
  { execution_id: 'exec-run', session_id: 'S1', state: 'running', bot_name: 'Nova', last_progress: '[Nova] Laying out the menu' },
  { execution_id: 'exec-fail', session_id: 'S1', state: 'failed', bot_name: 'Nova', last_progress: 'No verifiable result: nothing was produced' },
  { execution_id: 'exec-other', session_id: 'S2', state: 'running', bot_name: 'Rex', last_progress: 'someone else&apos;s chat' },
  { execution_id: '', session_id: 'S1', state: 'running' },
];
const messages = [
  { role: 'user', text: 'Plan a dinner party' },
  { role: 'assistant', text: 'On it — this is running now, and I\'ll share the result when it\'s ready.' },
];
const plan = flow.planDelegationRestore(rows, 'S1', messages);
checks.planFiltersToSession = plan.steps.length === 2 && plan.steps.every(s => s.id !== 'exec-other');
checks.planKeepsSettledRows = plan.steps.some(s => s.id === 'exec-fail' && s.status === 'failed');
checks.planKeepsRunningRows = plan.steps.some(s => s.id === 'exec-run' && s.status === 'running') && plan.anyRunning === true;
checks.planStripsWorkerTagFromLabel = plan.steps.find(s => s.id === 'exec-run').label === 'Laying out the menu';
checks.planAnchorsToLastAssistant = plan.anchorIdx === 1;

const settledPlan = flow.planDelegationRestore([rows[1]], 'S1', messages);
checks.settledPlanIsNotRunning = settledPlan.anyRunning === false && settledPlan.steps.length === 1;

// ---- merging: never clobber a richer existing step, always re-attach live ----
const activity = {
  thinking: '', expanded: false, cancelled: true, expectedHandoffCount: 0,
  steps: [{ kind: 'handoff', id: 'exec-fail', worker: 'Nova', label: 'Verified dinner-plan.pdf', status: 'completed' }],
};
flow.mergeRestoredSteps(activity, plan);
checks.mergeKeepsExistingVerifiedStep = activity.steps.find(s => s.id === 'exec-fail').label === 'Verified dinner-plan.pdf'
  && activity.steps.find(s => s.id === 'exec-fail').status === 'completed';
checks.mergeAddsMissingStep = activity.steps.some(s => s.id === 'exec-run' && s.status === 'running');
checks.mergeReattachesLive = activity.cancelled === false && activity.expanded === true
  && activity.expectedHandoffCount === 2;

// ---- chat.html wiring ----
// One restore path for every row, not a running-only one beside a
// verified-only one with a gap between them (delete-old-before-new).
checks.oldRunningOnlyRestoreGone = !html.includes('restoreRunningDelegations');
checks.restoreUsesSharedPlan = html.includes('planDelegationRestore') && html.includes('mergeRestoredSteps');
const restoreBody = html.split('async function restoreDelegationCards', 2)[1]?.split('function selectChat', 1)[0] || '';
checks.restoreExists = restoreBody.length > 0;
// Polling is for live work only — a settled card must not poll forever…
checks.pollsOnlyWhenRunning = /if\s*\(plan\.anyRunning\)\s*pollDelegations/.test(restoreBody);
// …and the restore must not keep a private terminal-state list that can
// drift from the module/server again.
checks.noPrivateTerminalListInRestore = !restoreBody.includes("'succeeded'");
checks.selectChatRestoresCards = html.includes('restoreDelegationCards(id, c.sessionId, selectionToken)');

const failures = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
if (failures.length > 0) throw new Error(`task-card revisit restore checks failed: ${failures.join(', ')}`);
process.stdout.write(`${JSON.stringify(checks)}\n`);
