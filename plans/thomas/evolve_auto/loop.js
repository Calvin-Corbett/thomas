export const meta = {
  name: 'evolve-auto',
  description: "Autonomous Evolve loop: Claude drives many fix-cycles overnight — each reproduces a real Thomas defect, fixes it on an isolated branch, verifies, and reports. Propose-only: never lands to dev.",
  phases: [
    { title: 'Fix', detail: 'worktree-isolated reproduce -> fix -> verify -> commit-to-branch per issue' },
    { title: 'Discover', detail: 'find fresh real defects when the curated backlog is done' },
    { title: 'Report', detail: 'write the morning review queue' },
  ],
}

const ROOT = 'C:\\Users\\corbe\\Thomas'

// Hard safety rules every cycle agent must obey unattended.
const RULES =
  `You are running UNATTENDED overnight while Calvin sleeps. Absolute rules:\n` +
  `- You are in your OWN isolated git worktree (a separate copy of ${ROOT}). Work only there.\n` +
  `- PROPOSE-ONLY: commit your fix to a NEW branch named evolve/auto-<id>. NEVER merge/push to dev or main. NEVER 'thomas ship'.\n` +
  `- Do NOT edit any file listed under [protected_files] in agent_safety.toml (gates, breakglass, shell.py, rules_of_road, skills_*). If your fix would need one, STOP: status='deferred', reason='needs protected-file change / Calvin tap'.\n` +
  `- NEVER use --no-verify. NEVER drive breakglass or set THOMAS_SKIP_BREAKGLASS. If a commit gate BLOCKS and needs human approval, do not bypass — status='deferred' with the gate name, and put your full diff in 'summary'.\n` +
  `- TEST-FIRST where feasible: write/lay out a check that FAILS for the stated reason, then fix, then show it pass. Run the relevant tests and 'ruff check' on every file you changed. Tag commits 'Thomas-Agent: claude'. If the enforcement-integrity or protected-files gate trips transiently, retry the commit ONCE.\n` +
  `- If you cannot make it verifiably better, status='failed' (do not commit a half-fix). Honesty over a green checkmark — no claim without proof.\n`

const CYCLE = {
  type: 'object',
  properties: {
    id: { type: 'string' },
    title: { type: 'string' },
    status: { type: 'string', enum: ['fixed', 'deferred', 'failed'] },
    verified: { type: 'boolean', description: 'true only if a test/ruff actually proved the fix' },
    branch: { type: 'string', description: "evolve/auto-<id> if committed, else ''" },
    proof: { type: 'string', description: 'how it was verified: test name + red->green, or ruff/syntax + manual note' },
    files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string', description: 'what changed and why, 2-4 sentences; if deferred/failed, the reason' },
  },
  required: ['id', 'title', 'status', 'verified', 'branch', 'proof', 'summary'],
}

// Curated backlog — concrete, mostly-independent, non-protected defects from the audit + Codex
// rankings + Calvin's conversations. Each: where to look + the done-signal.
const BACKLOG = [
  { id: 'mem-forget', title: 'Add a "forget X" memory path',
    task: `Thomas can remember + recall but has no way to FORGET. Add a forget tool mirroring remember/recall: a FORGET_TOOL in thomas/core/send_task_tool.py, a _forget_cb in thomas/marketplace/orchestrator/brain.py (delete/tombstone matching entries from the "user_memory" thread via the memory engine), wired in thomas/marketplace/specialists/reasoning.py like remember/recall, and a prompt line. Done: store a fact, forget it, recall returns nothing.` },
  { id: 'mem-async', title: 'Stop recall blocking the event loop',
    task: `In thomas/marketplace/orchestrator/brain.py the _recall_cb (and remember) call the SYNCHRONOUS memory engine (_mem.retrieve / add_event) directly inside an async function, blocking the event loop. Wrap those sync calls in asyncio.to_thread(...). Done: behavior unchanged (recall still works) and no sync DB call runs on the loop.` },
  { id: 'backstop-chitchat', title: 'Stop phantom tasks from chit-chat',
    task: `In thomas/marketplace/specialists/reasoning.py the _CLAIMS_HANDOFF_RE backstop can fire on casual phrases like "on it" and spawn a real task the user never asked for. Tighten the regex/logic so the backstop only completes a hand-off when the reply clearly claims a concrete task was sent (not a bare "on it"/"sure"). Add a unit test: a casual reply must NOT trigger a task_request.` },
  { id: 'stream-retry', title: 'One retry on a mid-stream model error',
    task: `On the gpt-5.5 chat path (thomas/marketplace/specialists/reasoning.py stream loop + thomas/server/routes/chat_v2.py), a single transient mid-stream error immediately ends the turn with "Sorry, I had trouble". Add ONE automatic retry/backoff on a mid-stream failure before surfacing that message. Keep it bounded (one retry). Add/adjust a test simulating one transient error -> turn recovers.` },
  { id: 'tool-risk-merge', title: 'Fix secret-vs-sandbox rule merge bug (Codex-flagged)',
    task: `In thomas/agent/tool_risk.py, when a command is BOTH destructive AND targets a secret file (e.g. "Remove-Item .env"), the classifier keeps the secret protection but DROPS the sandbox protection because it picks one rule instead of merging. Fix it to MERGE both protections. Add a test in tests/test_agent_tool_risk.py asserting both protections apply for such a command (red->green).` },
  { id: 'stall-ceiling', title: 'Real stall ceiling vs false "timed out after 120s"',
    task: `A dribbling/stalled model stream can hang well past the reported 120s and the timeout message misreports. Find the chat/worker stream timeout path and enforce a REAL wall-clock ceiling on a stream that stops producing tokens, with an honest message. Add a test for the stall-ceiling if feasible; otherwise verify by reading + ruff and describe the manual check.` },
  { id: 'announce-race', title: 'Lock announce-vs-chat concurrency',
    task: `In thomas/server/routes/chat_v2.py a "your task is done" announcement can fire mid-reply and corrupt the stream (gpt-5.5 hates concurrent streams). Serialize the announcement against an in-flight chat reply for the same session (a per-session lock/queue) so they never interleave. Add a test or a clear reasoned verification.` },
  { id: 'mem-confirm-honest', title: 'Recall: do not imply a save it did not make',
    task: `Audit the memory tool result strings in thomas/marketplace/specialists/reasoning.py for any remaining dishonest phrasing (claiming saved/recalled when it did not). Ensure every memory reply is strictly honest about what happened. Add a small test if feasible.` },
  { id: 'demo-data', title: 'Remove fake demo chats on fresh install',
    task: `In thomas/server/web/chat.html there is seeded/demo/placeholder conversation data (search "seed", "demo", "placeholder", "reordered the chain") that shows FAKE chats to a brand-new user. Make a fresh/first-run load show an EMPTY sidebar + empty conversation (no fabricated history). Do not break loading of the user's REAL saved chats. This is frontend: change carefully, verify by reading the load path + a JS syntax check, and describe the manual browser check in proof.` },
  { id: 'canvas-heartbeat', title: 'Canvas honest failure + progress heartbeat',
    task: `In thomas/server/chat_delegation_canvas.py and the canvas construct branch of thomas/server/web/chat.html: when the planner fails or times out, the canvas can sit as a frozen half-built shell forever, and long (~70s) builds show no progress. Add (a) a terminal "this didn't finish" state on failure/timeout and (b) a lightweight progress/heartbeat signal during a long build. Frontend+backend: verify by reading + syntax check; describe the manual check.` },
  { id: 'dead-buttons', title: 'Wire or hide dead first-run buttons',
    task: `In thomas/server/web/chat.html some message-action buttons (Copy/Retry/Search/PDF) do nothing on click. Either wire the easy ones (Copy = copy text; Retry = resend) or hide the ones that have no backend yet, so a new user sees no dead controls. Frontend: verify by reading + JS syntax check; describe the manual check.` },
  { id: 'needskey-models', title: 'Hide/disable models that 500 without a key',
    task: `In the model picker (thomas/server/web/chat.html + the models source) models that require an API key the user has not set are clickable and then 500. Disable/grey them (with a hint) instead of letting them error. Frontend: verify by reading + syntax check; describe the manual check.` },
]

phase('Fix')
log(`Autonomous Evolve loop starting: ${BACKLOG.length} curated defects, propose-only, worktree-isolated.`)

const round1 = await parallel(
  BACKLOG.map((item) => () =>
    agent(
      `Fix ONE Thomas defect end-to-end, then report.\n\n${RULES}\n\nISSUE [${item.id}] ${item.title}:\n${item.task}\n\n` +
      `Work in your worktree, reproduce-then-fix-then-verify, commit to branch evolve/auto-${item.id} if it passes ` +
      `(else deferred/failed per the rules). Return the structured result with real proof.`,
      { label: `fix:${item.id}`, phase: 'Fix', schema: CYCLE, isolation: 'worktree', effort: 'high' }
    )
  )
)
const r1 = round1.filter(Boolean)
log(`Round 1 done: ${r1.filter((x) => x.status === 'fixed').length} fixed, ${r1.filter((x) => x.status === 'deferred').length} deferred, ${r1.filter((x) => x.status === 'failed').length} failed.`)

// Round 2 — discover fresh real defects and fix a batch of them (bounded, no budget loop).
phase('Discover')
const discovery = await agent(
  `Hunt for 8 FRESH, concrete, fixable defects in the Thomas chat/server/agent code at ${ROOT} that are NOT in this ` +
  `already-handled list: ${BACKLOG.map((b) => b.id + ' (' + b.title + ')').join('; ')}. Prefer real bugs with a clear ` +
  `repro and a non-protected fix (logic errors, missing error handling, silent failures, race conditions, wrong ` +
  `defaults, untested edge cases). For each return an object {id (short-slug), title, task (a precise fix instruction ` +
  `with file paths + a done-signal)}. Avoid anything needing a protected-file edit or a Calvin tap. Return JSON array only.`,
  { label: 'discover:fresh', phase: 'Discover', effort: 'high',
    schema: { type: 'object', properties: { items: { type: 'array', items: {
      type: 'object', properties: { id: { type: 'string' }, title: { type: 'string' }, task: { type: 'string' } },
      required: ['id', 'title', 'task'] } } }, required: ['items'] } }
)
const fresh = (discovery?.items || []).slice(0, 8)
log(`Discovered ${fresh.length} fresh defects to fix.`)

const round2 = await parallel(
  fresh.map((item) => () =>
    agent(
      `Fix ONE Thomas defect end-to-end, then report.\n\n${RULES}\n\nISSUE [${item.id}] ${item.title}:\n${item.task}\n\n` +
      `Commit to branch evolve/auto-${item.id} if it passes. Return the structured result with real proof.`,
      { label: `fix:${item.id}`, phase: 'Fix', schema: CYCLE, isolation: 'worktree', effort: 'high' }
    )
  )
)
const r2 = round2.filter(Boolean)

const all = [...r1, ...r2]
phase('Report')
const report = await agent(
  `Write Calvin's MORNING REVIEW QUEUE for the autonomous Evolve loop's overnight run — plain English, decisive, skimmable. ` +
  `He reads this over coffee. Structure: (1) one-line headline (e.g. "9 branches ready to review, 2 deferred to you, 1 failed"); ` +
  `(2) a table of READY branches: id | what it fixes | verified? (proof) | branch name; (3) DEFERRED (what it refused to touch ` +
  `and why — protected file / needs your tap); (4) FAILED/dropped (what it tried and abandoned, honestly); (5) a one-line ` +
  `how-to: "review a branch with: git log --oneline dev..evolve/auto-<id>, then merge the ones you like." Be honest — ` +
  `unverified changes must be marked unverified. Results JSON:\n${JSON.stringify(all, null, 1)}`,
  { label: 'report', phase: 'Report', effort: 'high' }
)

return { headline: `ran ${all.length} cycles: ${all.filter((x) => x.status === 'fixed').length} fixed`, report, results: all }
