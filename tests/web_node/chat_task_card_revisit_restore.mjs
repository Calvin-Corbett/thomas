import { readChatFeatures } from './chat_feature_fixture.mjs';
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
const viewPath = process.argv[4];
const actionsPath = process.argv[5];
if (!htmlPath || !modulePath || !viewPath || !actionsPath) throw new Error('usage: node chat_task_card_revisit_restore.mjs <chat.html> <chat_turn_flow.js> <chat_activity_view.js> <chat_activity_actions.js>');
const html = readChatFeatures(htmlPath);
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
const buildPlan = flow.planDelegationRestore([
  { session_id: 'S1', execution_id: 'exec-build', state: 'running',
    runtime_profile: { build_conversation_id: 'build-42' }, last_progress: 'Reading task cards' },
], 'S1', messages);
checks.buildLinkSurvivesRevisit = buildPlan.steps[0].buildId === 'build-42';
const existingBuild = { steps: [{ kind: 'handoff', id: 'exec-build', label: 'Working', status: 'running' }] };
flow.mergeRestoredSteps(existingBuild, buildPlan);
checks.buildLinkSurvivesMerge = existingBuild.steps[0].buildId === 'build-42';

// A Thomas-project update marks itself "Build update: " so the server's
// humanizer leaves its text alone. That marker is provenance, not a sentence:
// the card already heads its list "Recorded in Build", so it must not repeat
// on the status line of every single update.
checks.progressLabelDropsInternalMarkers = flow.progressLabel('Build update: Rewriting the card') === 'Rewriting the card'
  && flow.progressLabel('[coding] Reading the card renderer') === 'Reading the card renderer'
  && flow.progressLabel('') === '' && flow.progressLabel(null) === '';
const markedPlan = flow.planDelegationRestore([
  { session_id: 'S1', execution_id: 'exec-marked', state: 'running', last_progress: 'Build update: Rewriting the card' },
], 'S1', messages);
checks.restoredLabelDropsBuildMarker = markedPlan.steps[0].label === 'Rewriting the card';

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

// ---- rendered card: the real activity template, not a mock-up ----
vm.runInContext(fs.readFileSync(viewPath, 'utf8'), context);
const view = context.window.ThomasChatActivityView.create({
  esc: s => String(s).replace(/</g, '&lt;').replace(/>/g, '&gt;'),
  deMd: s => s,
});
context.window.ThomasChatTurnFlow.partialArtifactsHTML = () => '';
const card = { activity: { steps: [{ ...buildPlan.steps[0] }], timeline: [
  { summary: 'Found the card history source', at: '2026-08-05T12:00:00Z' },
  { summary: 'Checking recorded progress', at: '2026-08-05T12:01:00Z' },
], expanded: false }, text: '', streaming: false };
const rendered = view.activityHTML(card);
checks.collapsedCardShowsRecordedUpdates = rendered.includes('Task updates · 2')
  && rendered.includes('Found the card history source') && rendered.includes('Checking recorded progress');
checks.collapsedCardOpensBuild = rendered.includes('data-open-build="build-42"');
checks.cardLabelsHistoryAsRecordedNotCompletion = rendered.includes('Recorded in Build')
  && rendered.includes('Latest recorded update') && rendered.includes('Earlier update')
  && rendered.includes('On it — working on this') && !rendered.includes('Task completed');
checks.emptyBuildCardDoesNotClaimUpdates = view.activityHTML({ ...card, activity: { ...card.activity, timeline: [] } })
  .includes('Waiting for recorded updates from Build.');
checks.unavailableBuildHistoryKeepsStatus = view.activityHTML({ ...card, activity: {
  ...card.activity, timeline: [], detailUnavailable: true,
} }).includes('Task history is temporarily unavailable; the current status is still shown above.');
checks.cardEscapesUntrustedUpdates = !view.activityHTML({ ...card, activity: { ...card.activity,
  timeline: [{ summary: '<img src=x onerror=alert(1)>' }] } }).includes('<img');
checks.cardConstrainsMobileWidth = rendered.includes('max-width:min(480px, 100%)')
  && rendered.includes('box-sizing:border-box');
// The header's second line is the task's STATUS. It used to read the newest
// line out of the recorded history instead — written before this panel existed,
// when the header was the only place that line could appear. The panel now sits
// directly under the header on a COLLAPSED card and heads the same line "Latest
// recorded update", so the card printed it twice: once ellipsised at 280px,
// once in full right below.
const headerStatusLine = html => (html.match(/max-width:280px;">([^<]*)</) || ['', ''])[1];
checks.headerShowsTheStatusNotACopyOfTheNewestUpdate = headerStatusLine(rendered) === 'Reading task cards'
  && (rendered.match(/Checking recorded progress/g) || []).length === 1;
// …and never the "[worker] " tag fetchActivityDetail adds to merged lines so a
// card's several handoffs can be told apart. This header is deliberately
// worker-free ("attribution lives in the expanded step detail"), so reading a
// merged line into it made it the one place that internal marker reached the
// reader — the same bracket form progressLabel and _card_step_summary strip.
const taggedBuildCard = view.activityHTML({ ...card, activity: { ...card.activity, steps: [
  { kind: 'handoff', id: 'exec-build', buildId: 'build-42', worker: 'Thomas', label: 'Rewriting the card', status: 'completed' },
  { kind: 'handoff', id: 'exec-build-2', buildId: 'build-43', worker: 'Thomas', label: 'Checking it', status: 'running' },
], timeline: [{ summary: '[Thomas] Rewrote the card', at: '2026-08-05T12:00:00Z' }] } });
checks.headerNeverPrintsTheMergedWorkerTag = !headerStatusLine(taggedBuildCard).includes('[Thomas]')
  && headerStatusLine(taggedBuildCard) === '1 of 2 finished'
  && taggedBuildCard.includes('[Thomas] Rewrote the card');
// A recorded step that stalled must say so, and say why — the blocker the
// server already returns was dropped, so a stuck run read like progress.
const blocked = view.activityHTML({ ...card, activity: { ...card.activity, timeline: [
  { summary: 'Ran the integration check', at: '2026-08-05T12:02:00Z', state: 'failed', blocker: 'Pass budget exhausted after 30 passes' },
] } });
checks.blockedUpdateShowsItsReason = blocked.includes('Blocked: Pass budget exhausted after 30 passes');
checks.blockedUpdateKeepsItsSummary = blocked.includes('Ran the integration check');
// A run the reader STOPPED is not one that failed. It is recorded with
// blocker="cancelled" (task_bot_runtime.cancel_execution), so the update that
// already says "Stopped by you." was also carrying a red "Blocked: cancelled".
const stoppedCard = view.activityHTML({ ...card, activity: { ...card.activity,
  steps: [{ ...buildPlan.steps[0], status: 'cancelled' }],
  timeline: [{ summary: 'Stopped by you.', at: '2026-08-05T12:03:00Z', state: 'cancelled', blocker: 'cancelled' }] } });
checks.stoppedUpdateKeepsItsSummary = stoppedCard.includes('Stopped by you.');
checks.stoppedUpdateIsNotShownAsBlocked = !stoppedCard.includes('Blocked:');
// …and not in failure colour either — the card header already reads "Stopped".
checks.stoppedUpdateIsNotPaintedAsAFailure = !stoppedCard.includes('#ff9a9a')
  && stoppedCard.includes('Stopped');
// A genuinely stalled step still gets the failure treatment it earned.
checks.failedUpdateIsStillPaintedAsAFailure = blocked.includes('#ff9a9a');

// Collapsed the card keeps the latest four; the rest are reachable by opening
// the card itself, not only by leaving Chat for Build.
const long = { ...card, activity: { ...card.activity, timeline: Array.from({ length: 7 },
  (_, i) => ({ summary: 'Recorded update ' + (i + 1), at: '2026-08-05T12:0' + i + ':00Z' })) } };
const collapsedLong = view.activityHTML(long);
checks.collapsedCardCapsAtFourUpdates = collapsedLong.includes('Task updates · 7')
  && collapsedLong.includes('Latest 4 of 7 updates') && !collapsedLong.includes('Recorded update 1')
  && collapsedLong.includes('Recorded update 7');
const expandedLong = view.activityHTML({ ...long, activity: { ...long.activity, expanded: true } });
checks.expandedCardShowsEveryUpdate = expandedLong.includes('Recorded update 1')
  && expandedLong.includes('Recorded update 7') && !expandedLong.includes('Latest 4 of 7 updates');
// …and getting there is a real control, not an instruction to click a header
// nothing marks as clickable — which is also the only keyboard route to it.
checks.moreUpdatesIsAControlNotAnInstruction = collapsedLong.includes('data-act-expand')
  && collapsedLong.includes('Show all 7') && !collapsedLong.includes('Open this card for the rest');
// The panel scrolls; a keyboard user needs a tab stop to scroll it.
checks.updatesPanelIsKeyboardScrollable = rendered.includes('tabindex="0"')
  && !view.activityHTML({ ...card, activity: { ...card.activity, timeline: [] } }).includes('tabindex="0"');

card.activity.expanded = true;
checks.expandedCardDoesNotDuplicateHistory = (view.activityHTML(card).match(/Found the card history source/g) || []).length === 1;
card.activity.expanded = false;

// ---- an ORDINARY worker card, with no Build conversation behind it ----
// Every dispatched task records transitions[]; the panel was gated on buildId,
// so the common card kept showing one status sentence with its whole recorded
// history sitting unread behind /detail.
const workerCard = { activity: { expanded: false, steps: [
  { kind: 'handoff', id: 'exec-run', worker: 'Nova', label: 'Plating the dinner plan', status: 'running' },
], timeline: [
  { summary: 'Getting started', at: '2026-08-05T12:00:00Z', state: 'queued' },
  { summary: 'Laying out the menu', at: '2026-08-05T12:01:00Z', state: 'in_progress' },
] }, text: '', streaming: false };
const workerHTML = view.activityHTML(workerCard);
checks.workerCardShowsItsRecordedUpdates = workerHTML.includes('Task updates · 2')
  && workerHTML.includes('Getting started') && workerHTML.includes('Laying out the menu');
// It has no Build conversation, so it must claim neither the link nor the source.
checks.workerCardNamesItsOwnSource = workerHTML.includes('Recorded as it happened')
  && !workerHTML.includes('Recorded in Build') && !workerHTML.includes('data-open-build');
checks.workerCardWaitsForItsFirstUpdate = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, timeline: [] } }).includes('Waiting for the first recorded update.');
// "Waiting" is only true while the task is still running. A settled task with
// an empty history has nothing more coming, so promising an update that can
// never arrive is an invented status.
const settledEmpty = view.activityHTML({ ...workerCard, activity: { ...workerCard.activity, timeline: [],
  steps: [{ kind: 'handoff', id: 'exec-run', worker: 'Nova', label: 'Plated', status: 'completed' }] } });
checks.settledCardWithNoHistorySaysSoInsteadOfWaiting =
  settledEmpty.includes('No updates were recorded before this task finished')
  && !settledEmpty.includes('Waiting for the first recorded update.');
// …and a read still in flight says that, rather than either of the two above.
checks.readInFlightSaysItIsReading = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, timeline: [], detailLoading: true } }).includes('Reading the recorded history…');
// An empty ARRAY is a read that came back with nothing; NO array is a read that
// has not happened yet. The card paints before its /detail request is issued,
// so an unread card must not answer the question it has not asked — a settled
// one was stating "no updates were recorded" for the width of the round trip,
// then filling in the history it had just denied.
const unread = view.activityHTML({ ...workerCard, activity: { ...workerCard.activity, timeline: undefined,
  steps: [{ kind: 'handoff', id: 'exec-run', worker: 'Nova', label: 'Plated', status: 'completed' }] } });
checks.unreadCardDoesNotClaimAnEmptyHistory = unread.includes('Reading the recorded history…')
  && !unread.includes('No updates were recorded before this task finished');
checks.unreadRunningCardDoesNotPromiseOneEither = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, timeline: undefined } }).includes('Reading the recorded history…');
// A card reads its history from EVERY handoff it has, so one source can answer
// while another does not. The card then holds part of the run and said nothing
// at all about it: the silent worker's lines were simply absent under a heading
// counting the ones that arrived, and with detailUnavailable false there was no
// "Try again" either.
const partialRead = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, detailPartial: true } });
checks.partialReadSaysWhatItIsMissing = partialRead.includes('Some of this task’s history could not be read; these are the updates that came back.')
  && partialRead.includes('Laying out the menu');
checks.partialReadOffersARetry = partialRead.includes('data-act-retry-detail') && partialRead.includes('Try again');
checks.partialReadReportsItsRetryInFlight = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, detailPartial: true, detailLoading: true } }).includes('Checking for newer updates…');
// …and where the sources that answered had nothing to say, the card must not
// fall back to "no updates were recorded" — the unread part is exactly where
// those updates would be.
const partialEmpty = view.activityHTML({ ...workerCard, activity: { ...workerCard.activity, timeline: [],
  detailPartial: true, steps: [{ kind: 'handoff', id: 'exec-run', worker: 'Nova', label: 'Plated', status: 'completed' }] } });
checks.partialReadWithNothingBackDoesNotClaimAnEmptyHistory =
  partialEmpty.includes('Some of this task’s history could not be read; no updates came back from the rest.')
  && !partialEmpty.includes('No updates were recorded before this task finished')
  && partialEmpty.includes('data-act-retry-detail');
// The card is rebuilt from innerHTML wholesale — a running one every three
// seconds — so its status lines are new nodes on every paint, and a live region
// that is re-inserted is announced again. An unchanged "Waiting for the first
// recorded update." was read out to a screen reader every three seconds for as
// long as the task ran.
const speaking = { ...workerCard.activity, timeline: [] };
checks.aStatusLineIsAnnouncedWhenItAppears = view.activityHTML({ ...workerCard, activity: speaking }).includes('role="status"');
checks.anUnchangedStatusLineIsNotAnnouncedAgain = !view.activityHTML({ ...workerCard, activity: speaking }).includes('role="status"');
speaking.detailUnavailable = true;
checks.aChangedStatusLineIsAnnouncedAgain = view.activityHTML({ ...workerCard, activity: speaking }).includes('role="status"');
const workerExpanded = view.activityHTML({ ...workerCard, activity: { ...workerCard.activity, expanded: true } });
checks.workerCardDoesNotPrintHistoryTwice = (workerExpanded.match(/Laying out the menu/g) || []).length === 1
  && !workerExpanded.includes('Step by step');
// The steer box is what expanding a running card is FOR — it must survive the
// detail section no longer printing its own copy of the timeline.
checks.workerCardKeepsItsSteerBox = workerExpanded.includes('data-steer-form');
// A card can hold SEVERAL handoffs, and the panel shows their MERGED history
// (fetchActivityDetail reads each one and tags its lines with the worker). So
// "Recorded in Build" is only true when every source was a Build run — on a
// mixed card it claimed a home in Build for worker lines that never had one,
// and the "Open in Build" button follows the last handoff, so there was not
// even a way to go and look.
const mixedCard = view.activityHTML({ ...workerCard, activity: { ...workerCard.activity, steps: [
  { kind: 'handoff', id: 'exec-build', buildId: 'build-42', worker: 'Thomas', label: 'Rewriting the card', status: 'completed' },
  { kind: 'handoff', id: 'exec-run', worker: 'Nova', label: 'Costing the ingredients', status: 'running' },
], timeline: [
  { summary: '[Thomas] Rewrote the card', at: '2026-08-05T12:00:00Z', state: 'completed' },
  { summary: '[Nova] Costing the ingredients', at: '2026-08-05T12:01:00Z', state: 'in_progress' },
] } });
checks.mixedSourceCardDoesNotClaimTheyAreAllInBuild = mixedCard.includes('Recorded as it happened')
  && !mixedCard.includes('Recorded in Build') && mixedCard.includes('Task updates · 2');
// …and where every source IS a Build run, it still says so.
checks.allBuildSourcesStillNameBuild = view.activityHTML({ ...workerCard, activity: { ...workerCard.activity, steps: [
  { kind: 'handoff', id: 'exec-build', buildId: 'build-42', worker: 'Thomas', label: 'Rewriting the card', status: 'completed' },
  { kind: 'handoff', id: 'exec-build-2', buildId: 'build-43', worker: 'Thomas', label: 'Checking it', status: 'running' },
] } }).includes('Recorded in Build');
// A card with no delegation id has nothing to read: no panel, no empty promise.
checks.cardWithoutADelegationShowsNoUpdatesPanel = !view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, steps: [{ kind: 'tool', label: 'reading files', status: 'running' }] } })
  .includes('Task updates');

// ---- auto-fetch: a rendered Build card requests its detail without a click ----
const fetches = [];
context.fetch = async url => { fetches.push(url); return { ok: true, json: async () => ({ ok: true, steps: [
  { summary: 'Recorded step', at: '2026-08-05T12:01:00Z' },
] }) }; };
vm.runInContext(fs.readFileSync(actionsPath, 'utf8'), context);
const buildActivity = { steps: [{ ...buildPlan.steps[0] }] };
const state = { sessionId: 'S1', messages: [{ activity: buildActivity }] };
const activityEl = { innerHTML: '', querySelector: () => null, querySelectorAll: () => [], contains: () => false };
const actions = context.window.ThomasChatActivityActions.create({ state, msgRefs: [{ activityEl }],
  activityHTML: () => '', captureConversation: () => () => true });
actions.renderActivity(0);
await new Promise(resolve => setTimeout(resolve, 0));
checks.buildCardFetchesWithoutExpansion = fetches.length === 1
  && fetches[0].includes('/exec-build/detail') && buildActivity.timeline?.[0]?.summary === 'Recorded step';

// …and so does a card whose delegation is an ordinary worker.
const plainActivity = { steps: [{ kind: 'handoff', id: 'exec-plain', status: 'running' }] };
const plainActions = context.window.ThomasChatActivityActions.create({
  state: { sessionId: 'S1', messages: [{ activity: plainActivity }] },
  msgRefs: [{ activityEl: { innerHTML: '', querySelector: () => null, querySelectorAll: () => [], contains: () => false } }],
  activityHTML: () => '', captureConversation: () => () => true,
});
plainActions.renderActivity(0);
await new Promise(resolve => setTimeout(resolve, 0));
checks.workerCardFetchesItsHistoryWithoutExpansion = fetches.some(url => url.includes('/exec-plain/detail'))
  && plainActivity.timeline?.[0]?.summary === 'Recorded step';

// ---- an open history must not jump back to its oldest line on every poll ----
const section = { scrollTop: 600, scrollHeight: 900, clientHeight: 300 };
const scrollEl = { innerHTML: '', contains: () => false, querySelectorAll: () => [],
  querySelector: sel => (sel === '[aria-label="Task updates"]' ? section : null) };
const scrollActivity = { steps: [{ kind: 'handoff', id: 'exec-scroll', status: 'running' }] };
const scrollActions = context.window.ThomasChatActivityActions.create({
  state: { sessionId: 'S1', messages: [{ activity: scrollActivity }] },
  msgRefs: [{ activityEl: scrollEl }], activityHTML: () => '', captureConversation: () => () => true,
});
scrollActions.renderActivity(0);
checks.newUpdatesStayPinnedToTheNewestLine = section.scrollTop === 900;
section.scrollTop = 120; // the reader went back through the history
scrollActions.renderActivity(0);
checks.readerScrolledBackIsLeftWhereTheyAre = section.scrollTop === 120;
// "Show all" reveals the OLDER updates, and they sit ABOVE the ones already on
// screen. Pinning to the newest line there would land the reader back on the
// same four they could already see, leaving the only control that reaches the
// rest of the history looking dead.
scrollActivity.showAllUpdates = true;
scrollActions.renderActivity(0);
checks.showAllLandsOnTheRevealedUpdates = section.scrollTop === 0;
// …and that is a one-shot: the next poll goes back to following the newest line.
section.scrollTop = 900;
scrollActions.renderActivity(0);
checks.showAllDoesNotStickAcrossPolls = scrollActivity.showAllUpdates === false && section.scrollTop === 900;

// ---- a task record that is GONE is not a transient read failure ----
// Deleting a chat sweeps its task records, so an old card's /detail is a 404
// forever; promising "temporarily unavailable" and retrying every 15s is both
// untrue and pointless.
const goneActivity = { steps: [{ kind: 'handoff', id: 'exec-gone', status: 'completed' }] };
const goneActions = context.window.ThomasChatActivityActions.create({
  state: { sessionId: 'S1', messages: [{ activity: goneActivity }] },
  msgRefs: [{ activityEl: { innerHTML: '', querySelector: () => null, querySelectorAll: () => [], contains: () => false } }],
  activityHTML: () => '', captureConversation: () => () => true,
});
context.fetch = async () => ({ ok: false, status: 404 });
await goneActions.fetchActivityDetail(0);
checks.goneTaskRecordIsNotRetriedForever = goneActivity.detailMissing === true
  && goneActivity.detailRetryAt === Number.MAX_SAFE_INTEGER;
context.fetch = async () => ({ ok: false, status: 503 });
const flakyActivity = { steps: [{ kind: 'handoff', id: 'exec-flaky', status: 'running' }] };
const flakyActions = context.window.ThomasChatActivityActions.create({
  state: { sessionId: 'S1', messages: [{ activity: flakyActivity }] },
  msgRefs: [{ activityEl: { innerHTML: '', querySelector: () => null, querySelectorAll: () => [], contains: () => false } }],
  activityHTML: () => '', captureConversation: () => () => true,
});
await flakyActions.fetchActivityDetail(0);
checks.flakyReadStillRetries = flakyActivity.detailMissing === false
  && flakyActivity.detailRetryAt > Date.now() && flakyActivity.detailRetryAt < Number.MAX_SAFE_INTEGER;
// A SETTLED card's failed read had no second chance at all: detailRetryAt was
// honoured only by the delegation poll, which runs while a task is running, so
// a finished task read once, missed, and promised "temporarily unavailable"
// forever. Once the backoff passes, the next render asks again.
let strandedCalls = 0;
context.fetch = async () => {
  strandedCalls++;
  if (strandedCalls === 1) return { ok: false, status: 503 };
  return { ok: true, json: async () => ({ ok: true, steps: [{ summary: 'Read on the second try', at: '2026-08-05T12:03:00Z' }] }) };
};
const strandedActivity = { steps: [{ kind: 'handoff', id: 'exec-stranded', status: 'completed' }] };
const strandedActions = context.window.ThomasChatActivityActions.create({
  state: { sessionId: 'S1', messages: [{ activity: strandedActivity }] },
  msgRefs: [{ activityEl: { innerHTML: '', querySelector: () => null, querySelectorAll: () => [], contains: () => false } }],
  activityHTML: () => '', captureConversation: () => () => true,
});
await strandedActions.fetchActivityDetail(0);
checks.settledCardBacksOffAfterAFailedRead = strandedActivity.detailUnavailable === true && strandedCalls === 1;
strandedActions.renderActivity(0);
await new Promise(resolve => setTimeout(resolve, 0));
checks.settledCardDoesNotRetryBeforeItsBackoff = strandedCalls === 1;
strandedActivity.detailRetryAt = Date.now() - 1;
strandedActions.renderActivity(0);
await new Promise(resolve => setTimeout(resolve, 0));
checks.settledCardRetriesOnceItsBackoffPasses = strandedCalls === 2
  && strandedActivity.detailUnavailable === false
  && strandedActivity.timeline?.[0]?.summary === 'Read on the second try';
// The record the server says is GONE must still never be asked for again.
checks.goneRecordIsNeverDueAgain = strandedActions._detailReadDue({
  steps: [{ kind: 'handoff', id: 'x' }], detailUnavailable: true, detailMissing: true,
  detailRetryAt: Number.MAX_SAFE_INTEGER,
}) === false;

checks.goneHistorySaysItIsGone = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, timeline: [], detailUnavailable: true, detailMissing: true } })
  .includes('No recorded history is kept for this task');

// ---- "temporarily unavailable" has to be backed by a retry you can reach ----
// The delegation poll is the only automatic retry and it runs solely while a
// task is running, so on a settled card that word promised something nothing
// kept unless the reader guessed the card header was clickable.
const unavailableEmpty = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, timeline: [], detailUnavailable: true } });
checks.unavailableHistoryOffersARetry = unavailableEmpty.includes('data-act-retry-detail')
  && unavailableEmpty.includes('Try again');
const partialUnavailable = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, detailUnavailable: true } });
checks.partialHistoryOffersARetryToo = partialUnavailable.includes('data-act-retry-detail')
  && partialUnavailable.includes('Latest task history is temporarily unavailable')
  && partialUnavailable.includes('Laying out the menu');
// A card that already has history must also report the retry in flight, or
// "Try again" removes itself and nothing else on screen changes.
const partialRetrying = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, detailUnavailable: true, detailLoading: true } });
checks.partialHistoryReportsItsRetryInFlight = partialRetrying.includes('Checking for newer updates…')
  && !partialRetrying.includes('data-act-retry-detail')
  && !partialRetrying.includes('Latest task history is temporarily unavailable');
// A healthy card refreshes every few seconds; that must not flash a notice.
checks.healthyRefreshShowsNoNotice = !view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, detailLoading: true } }).includes('Checking for newer updates…');
// …and it says so in a whole sentence: this notice read "No task record is kept
// for this any more", a line missing its own noun, in the one panel whose entire
// job is the words the card shows the reader.
checks.goneRecordWithHistorySaysWhatItHas = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, detailUnavailable: true, detailMissing: true } })
  .includes('No task record is kept for this task any more; these are the updates already read.');
// A record the server says is gone has nothing to retry, and a read already in
// flight needs no second one — either button would be a lie about the state.
checks.goneHistoryOffersNoRetry = !view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, timeline: [], detailUnavailable: true, detailMissing: true } })
  .includes('data-act-retry-detail');
const retrying = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, timeline: [], detailUnavailable: true, detailLoading: true } });
checks.retryInFlightSaysItIsReading = retrying.includes('Reading the recorded history…')
  && !retrying.includes('data-act-retry-detail')
  && !retrying.includes('Task history is temporarily unavailable');

// …and clicking it reads again straight away, instead of waiting out a backoff
// the reader has just overridden by asking.
let askedReads = 0;
context.fetch = async () => {
  askedReads++;
  if (askedReads === 1) return { ok: false, status: 503 };
  return { ok: true, json: async () => ({ ok: true, steps: [{ summary: 'Read when asked again', at: '2026-08-05T12:05:00Z' }] }) };
};
const askedActivity = { steps: [{ kind: 'handoff', id: 'exec-asked', status: 'completed' }] };
const retryButton = { listener: null, addEventListener: (_, fn) => { retryButton.listener = fn; } };
const paints = [];
const askedActions = context.window.ThomasChatActivityActions.create({
  state: { sessionId: 'S1', messages: [{ activity: askedActivity }] },
  msgRefs: [{ activityEl: { innerHTML: '', contains: () => false, querySelectorAll: () => [],
    querySelector: sel => (sel === '[data-act-retry-detail]' ? retryButton : null) } }],
  activityHTML: m => { paints.push(!!m.activity.detailLoading); return ''; },
  captureConversation: () => () => true,
});
await askedActions.fetchActivityDetail(0);
checks.failedReadWiresItsRetryControl = typeof retryButton.listener === 'function'
  && askedActivity.detailUnavailable === true && askedReads === 1;
paints.length = 0;
retryButton.listener({ stopPropagation: () => {} });
// The repaint must happen as the read starts, or the click visibly does nothing.
checks.retryRepaintsAsReadingImmediately = paints.includes(true);
await new Promise(resolve => setTimeout(resolve, 0));
checks.retryReadsWithoutWaitingOutTheBackoff = askedReads === 2
  && askedActivity.detailUnavailable === false
  && askedActivity.timeline?.[0]?.summary === 'Read when asked again';

// ---- one source answering while another does not is not a complete read ----
// fetchActivityDetail reads EVERY handoff with an id and merges them. A single
// source replying set detailUnavailable = false and the backoff to zero, so a
// card whose other worker never answered showed half its run as the whole of
// it, with nothing to say so and no retry to fix it.
const partialSource = { activity: { steps: [
  { kind: 'handoff', id: 'part-a', status: 'completed' },
  { kind: 'handoff', id: 'part-b', status: 'completed' },
] } };
let partBReads = 0;
context.fetch = async url => {
  if (url.includes('/part-a/detail')) return { ok: true, json: async () => ({ ok: true, bot_name: 'Thomas',
    steps: [{ summary: 'Rewrote the card', at: '2026-08-05T12:00:00Z' }] }) };
  partBReads++;
  if (partBReads === 1) return { ok: false, status: 503 };
  return { ok: true, json: async () => ({ ok: true, bot_name: 'Nova',
    steps: [{ summary: 'Checked it in the browser', at: '2026-08-05T12:01:00Z' }] }) };
};
const partialActions = context.window.ThomasChatActivityActions.create({
  state: { sessionId: 'S1', messages: [partialSource] },
  msgRefs: [{ activityEl: { innerHTML: '', querySelector: () => null, querySelectorAll: () => [], contains: () => false } }],
  activityHTML: () => '', captureConversation: () => () => true,
});
await partialActions.fetchActivityDetail(0);
const partial = partialSource.activity;
checks.oneSourceFailingKeepsWhatTheOtherSaid = partial.timeline.length === 1
  && partial.timeline[0].summary === '[Thomas] Rewrote the card';
checks.aPartialReadIsNotReportedAsComplete = partial.detailPartial === true
  && partial.detailUnavailable === false && partial.detailMissing === false;
checks.aPartialReadIsStillOwedAnother = partialActions._detailReadDue(partial) === false
  && partial.detailRetryAt > Date.now() && partial.detailRetryAt < Number.MAX_SAFE_INTEGER;
partial.detailRetryAt = Date.now() - 1;
checks.aPartialReadIsDueOnceItsBackoffPasses = partialActions._detailReadDue(partial) === true;
await partialActions.fetchActivityDetail(0);
checks.theSecondReadCompletesTheHistory = partial.detailPartial === false && partial.detailRetryAt === 0
  && partial.timeline.map(s => s.summary).join(' | ') === '[Thomas] Rewrote the card | [Nova] Checked it in the browser';
// A read that THROWS partway must not carry the sources it already read out of
// scope with it — the card fell back to "temporarily unavailable" while holding
// a complete answer from the source that did reply.
const thrownSource = { activity: { steps: [
  { kind: 'handoff', id: 'throw-a', status: 'completed' },
  { kind: 'handoff', id: 'throw-b', status: 'completed' },
] } };
context.fetch = async url => {
  if (url.includes('/throw-a/detail')) return { ok: true, json: async () => ({ ok: true, bot_name: 'Thomas',
    steps: [{ summary: 'Read before the network went', at: '2026-08-05T12:00:00Z' }] }) };
  throw new Error('network');
};
const thrownActions = context.window.ThomasChatActivityActions.create({
  state: { sessionId: 'S1', messages: [thrownSource] },
  msgRefs: [{ activityEl: { innerHTML: '', querySelector: () => null, querySelectorAll: () => [], contains: () => false } }],
  activityHTML: () => '', captureConversation: () => () => true,
});
await thrownActions.fetchActivityDetail(0);
checks.aThrownReadKeepsWhatItAlreadyRead = thrownSource.activity.timeline?.[0]?.summary === '[Thomas] Read before the network went'
  && thrownSource.activity.detailUnavailable === false
  && thrownSource.activity.detailPartial === true;
// A source the server reports GONE is not a part-read to retry: nothing comes
// back next time either, so the card must not sit on "Try again" forever.
const goneAmongThem = { activity: { steps: [
  { kind: 'handoff', id: 'kept-a', status: 'completed' },
  { kind: 'handoff', id: 'swept-b', status: 'completed' },
] } };
context.fetch = async url => {
  if (url.includes('/kept-a/detail')) return { ok: true, json: async () => ({ ok: true, bot_name: 'Thomas',
    steps: [{ summary: 'Rewrote the card', at: '2026-08-05T12:00:00Z' }] }) };
  return { ok: false, status: 404 };
};
const goneAmongActions = context.window.ThomasChatActivityActions.create({
  state: { sessionId: 'S1', messages: [goneAmongThem] },
  msgRefs: [{ activityEl: { innerHTML: '', querySelector: () => null, querySelectorAll: () => [], contains: () => false } }],
  activityHTML: () => '', captureConversation: () => () => true,
});
await goneAmongActions.fetchActivityDetail(0);
checks.aSweptSourceIsNotTreatedAsAPartialRead = goneAmongThem.activity.detailPartial === false
  && goneAmongThem.activity.detailRetryAt === 0
  && goneAmongThem.activity.timeline.length === 1;
// …but a source swept AFTER its lines were already read must not take them off
// the card with it. A gone record is deliberately not a part-read, so keying
// the append-only merge on detailPartial alone let exactly this card drop from
// two updates to one between two polls, with no notice and a heading that then
// counted only the survivor. What the reader has already been shown was
// recorded, and stays true.
const sweptLater = { activity: { steps: [
  { kind: 'handoff', id: 'live-a', status: 'completed' },
  { kind: 'handoff', id: 'later-b', status: 'completed' },
] } };
let laterSwept = false;
context.fetch = async url => {
  if (url.includes('/live-a/detail')) return { ok: true, json: async () => ({ ok: true, bot_name: 'Thomas',
    steps: [{ summary: 'Rewrote the card', at: '2026-08-05T12:00:00Z' }] }) };
  if (laterSwept) return { ok: false, status: 404 };
  return { ok: true, json: async () => ({ ok: true, bot_name: 'Nova',
    steps: [{ summary: 'Checked it in the browser', at: '2026-08-05T12:01:00Z' }] }) };
};
const sweptLaterActions = context.window.ThomasChatActivityActions.create({
  state: { sessionId: 'S1', messages: [sweptLater] },
  msgRefs: [{ activityEl: { innerHTML: '', querySelector: () => null, querySelectorAll: () => [], contains: () => false } }],
  activityHTML: () => '', captureConversation: () => () => true,
});
await sweptLaterActions.fetchActivityDetail(0);
checks.bothSourcesReadGiveTheMergedHistory = sweptLater.activity.timeline.length === 2
  && sweptLater.activity.detailPartial === false;
laterSwept = true;
await sweptLaterActions.fetchActivityDetail(0);
checks.aSourceSweptLaterDoesNotTakeItsReadLinesWithIt =
  sweptLater.activity.timeline.map(s => s.summary).join(' | ')
    === '[Thomas] Rewrote the card | [Nova] Checked it in the browser'
  && sweptLater.activity.detailPartial === false
  && sweptLater.activity.detailMissing === false;

// ---- a temporary detail failure cannot strand an actively updating card ----
vm.runInContext(fs.readFileSync(new URL('../../thomas/server/web/js/chat_delegation_updates.js', import.meta.url), 'utf8'), context);
let polling = 0;
const recorded = buildActivity.timeline[0];
context.setTimeout = resolve => setTimeout(resolve, 0);
context.fetch = async url => {
  if (url.endsWith('/delegations')) {
    polling++;
    if (polling === 2) buildActivity.detailRetryAt = Date.now() - 1;
    return { ok: true, json: async () => ({ delegations: [] }) };
  }
  if (url.endsWith('/detail') && polling === 1) return { ok: false };
  if (url.endsWith('/detail')) return { ok: true, json: async () => {
    buildActivity.steps[0].status = 'failed'; // settle after the recorded update
    return { ok: true, steps: [recorded, { summary: 'Verified files on disk', at: '2026-08-05T12:02:00Z' }] };
  } };
  throw new Error('unexpected URL: ' + url);
};
const updates = context.window.ThomasChatDelegationUpdates.create({
  state, captureConversation: () => () => true, canvasState: {},
  reconcileHandoff: () => {}, renderActivity: actions.renderActivity,
  fetchActivityDetail: actions.fetchActivityDetail,
});
await updates.pollDelegations(0);
checks.failedReadKeepsLastRecordedUpdate = recorded.summary === buildActivity.timeline?.[0]?.summary;
checks.pollRetriesAndShowsNewEvidence = polling >= 2 && buildActivity.detailUnavailable === false
  && buildActivity.timeline?.[1]?.summary === 'Verified files on disk';

// ---- the repaint must not take the keyboard with it ----
// The card is rebuilt wholesale from innerHTML, and a running task rebuilds it
// every three seconds, so every control in it is destroyed under whoever is
// standing on one — the ✕ that stops the task, and the tab stop this panel was
// given so its scroll is reachable without a pointer. Focus fell to the
// document body and the next Tab restarted from the top of the page.
const fakeNode = attrs => {
  const node = {
    hasAttribute: n => Object.prototype.hasOwnProperty.call(attrs, n),
    getAttribute: n => (Object.prototype.hasOwnProperty.call(attrs, n) ? attrs[n] : null),
    addEventListener: () => {},
    focusCount: 0, focusOpts: null, scrollTop: 0, scrollHeight: 400, clientHeight: 200,
  };
  node.focus = opts => { node.focusCount++; node.focusOpts = opts; };
  return node;
};
const focusCard = (nodes, contained = true) => ({
  innerHTML: '', querySelectorAll: () => [], contains: () => contained,
  querySelector: sel => (Object.prototype.hasOwnProperty.call(nodes, sel) ? nodes[sel] : null),
});
// timeline: [] is a read that already came back, so rendering never starts a fetch.
const focusActions = (activity, el) => context.window.ThomasChatActivityActions.create({
  state: { sessionId: 'S1', messages: [{ activity }] }, msgRefs: [{ activityEl: el }],
  activityHTML: () => '', captureConversation: () => () => true,
});
const runningStep = extra => ({ steps: [{ kind: 'handoff', id: 'exec-focus', status: 'running' }], timeline: [], ...extra });

const liveCancel = fakeNode({ 'data-act-cancel': '' });
const liveCard = focusCard({ '[data-act-cancel]': liveCancel });
context.document.activeElement = liveCancel;
focusActions(runningStep(), liveCard).renderActivity(0);
checks.pollHandsTheCancelButtonBackItsFocus = liveCancel.focusCount === 1
  && !!liveCancel.focusOpts && liveCancel.focusOpts.preventScroll === true;

// A control the press REMOVED hands focus to the panel, which is where the
// result of the press is written — "Show all" has just revealed the rest of
// the history, so the keyboard belongs in it, not on the document body.
const goneExpand = fakeNode({ 'data-act-expand': '' });
const expandPanel = fakeNode({ tabindex: '0', 'aria-label': 'Task updates' });
context.document.activeElement = goneExpand;
focusActions({ steps: [{ kind: 'handoff', id: 'exec-focus', status: 'completed' }], timeline: [], expanded: true },
  focusCard({ '[aria-label="Task updates"]': expandPanel })).renderActivity(0);
checks.showAllHandsFocusToTheUpdatesItRevealed = expandPanel.focusCount === 1 && goneExpand.focusCount === 0;

// "Try again" on a card with NO history removes itself for a read in flight,
// and that card's panel has no tab stop (nothing to scroll) — so the status
// line that replaced the button takes the focus instead.
const goneRetry = fakeNode({ 'data-act-retry-detail': '' });
const readingLine = fakeNode({ 'data-act-status': '', tabindex: '-1' });
context.document.activeElement = goneRetry;
focusActions({ steps: [{ kind: 'handoff', id: 'exec-focus', status: 'completed' }], timeline: [],
  detailUnavailable: true, detailLoading: true }, focusCard({ '[data-act-status]': readingLine })).renderActivity(0);
checks.retryHandsFocusToTheLineThatReplacedIt = readingLine.focusCount === 1;

// …and the repaint that DELIVERS that read must not drop the keyboard again.
// The status line is a target this module chose to park focus on, so it has to
// be one this module can find again. It was not: the reader who pressed "Try
// again" was put on the reading line and then dropped to the document body on
// the very paint they were waiting for, when the history arrived and replaced
// it. The panel holding that history is where they belong.
const deliveredPanel = fakeNode({ tabindex: '0', 'aria-label': 'Task updates' });
const deliveredLine = fakeNode({ 'data-act-status': '', tabindex: '-1' });
context.document.activeElement = deliveredLine;
focusActions({ steps: [{ kind: 'handoff', id: 'exec-focus', status: 'completed' }],
  timeline: [{ summary: 'Read when asked again', at: '2026-08-05T12:05:00Z' }] },
  focusCard({ '[aria-label="Task updates"]': deliveredPanel })).renderActivity(0);
checks.theArrivingHistoryKeepsTheKeyboardThatAskedForIt = deliveredPanel.focusCount === 1;

// The panel is a tab stop precisely so its scroll is reachable without a
// pointer, and a running card repaints every three seconds — so the plainest
// case of all is the reader standing IN the history while it grows.
const keptPanel = fakeNode({ tabindex: '0', 'aria-label': 'Task updates' });
context.document.activeElement = keptPanel;
focusActions({ steps: [{ kind: 'handoff', id: 'exec-focus', status: 'running' }],
  timeline: [{ summary: 'Laying out the menu', at: '2026-08-05T12:01:00Z' }] },
  focusCard({ '[aria-label="Task updates"]': keptPanel })).renderActivity(0);
checks.theUpdatesPanelKeepsItsOwnFocusAcrossAPoll = keptPanel.focusCount === 1
  && !!keptPanel.focusOpts && keptPanel.focusOpts.preventScroll === true;

// …and the panel outlives its own tab stop, which is the trap: the section is
// still in the markup after a paint with nothing left to scroll, but it carries
// no tabindex then, so focusing it is a no-op and the keyboard ends up on the
// document body. Finding the target again is not enough — it has to still be
// able to hold focus. The status line that replaced the history can.
const emptiedPanel = fakeNode({ 'aria-label': 'Task updates' });
const emptiedLine = fakeNode({ 'data-act-status': '', tabindex: '-1' });
context.document.activeElement = emptiedPanel;
focusActions({ steps: [{ kind: 'handoff', id: 'exec-focus', status: 'completed' }], timeline: [] },
  focusCard({ '[aria-label="Task updates"]': emptiedPanel, '[data-act-status]': emptiedLine })).renderActivity(0);
checks.aPanelThatLostItsTabStopHandsFocusToTheLine = emptiedLine.focusCount === 1
  && emptiedPanel.focusCount === 0;

// Pressing ✕ leaves the button in place but disabled; a disabled control
// cannot hold focus, so it passes it on rather than dropping it.
const cancelling = fakeNode({ 'data-act-cancel': '' });
cancelling.disabled = true;
const cancellingPanel = fakeNode({ tabindex: '0', 'aria-label': 'Task updates' });
context.document.activeElement = cancelling;
focusActions(runningStep({ cancelling: true }),
  focusCard({ '[data-act-cancel]': cancelling, '[aria-label="Task updates"]': cancellingPanel })).renderActivity(0);
checks.aDisabledCancelHandsFocusOnRatherThanDroppingIt = cancelling.focusCount === 0
  && cancellingPanel.focusCount === 1;

// Several cards poll at once, so a repaint must only ever restore focus it
// actually took: one card's poll must not pull the keyboard off another's.
const elsewhere = fakeNode({ 'data-act-cancel': '' });
const otherCancel = fakeNode({ 'data-act-cancel': '' });
context.document.activeElement = elsewhere;
focusActions(runningStep(), focusCard({ '[data-act-cancel]': otherCancel }, false)).renderActivity(0);
checks.aRepaintNeverStealsFocusFromAnotherCard = otherCancel.focusCount === 0 && elsewhere.focusCount === 0;

// …and the older guard still stands ahead of all of it: a steer note being
// typed blocks the repaint outright rather than being restored after it.
const steerInput = fakeNode({ 'data-steer-input': '' });
const steerCard = focusCard({});
steerCard.innerHTML = 'kept';
context.document.activeElement = steerInput;
focusActions(runningStep(), steerCard).renderActivity(0);
checks.typingASteerNoteStillBlocksTheRepaint = steerCard.innerHTML === 'kept';
context.document.activeElement = null;

// The fallback target has to exist in the real markup: the panel carries a tab
// stop only once there are updates to scroll, so the empty line carries
// tabindex="-1" to be reachable programmatically without becoming one.
checks.emptyUpdatesLineCanReceiveFocus = view.activityHTML({ ...workerCard, activity: {
  ...workerCard.activity, timeline: [], detailUnavailable: true } }).includes('data-act-status tabindex="-1"');

// ---- chat.html wiring ----
// One restore path for every row, not a running-only one beside a
// verified-only one with a gap between them (delete-old-before-new).
checks.oldRunningOnlyRestoreGone = !html.includes('restoreRunningDelegations');
checks.restoreUsesSharedPlan = html.includes('planDelegationRestore') && html.includes('mergeRestoredSteps');
const restoreBody = html.split('async function restoreDelegationCards', 2)[1]?.split('function selectChat', 1)[0] || '';
checks.restoreExists = restoreBody.length > 0;
// Polling is for live work only — a settled card must not poll forever…
checks.pollsOnlyWhenRunning = /if\s*\(plan\.anyRunning\)\s*deps\.pollDelegations/.test(restoreBody);
// …and the restore must not keep a private terminal-state list that can
// drift from the module/server again.
checks.noPrivateTerminalListInRestore = !restoreBody.includes("'succeeded'");
checks.selectChatRestoresCards = html.includes('restoreDelegationCards(id, c.sessionId, selectionToken)');

const failures = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
if (failures.length > 0) throw new Error(`task-card revisit restore checks failed: ${failures.join(', ')}`);
process.stdout.write(`${JSON.stringify(checks)}\n`);
