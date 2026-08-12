export const meta = {
  name: 'evolve-auto-round',
  description: 'One recurring round of the autonomous Evolve loop: discover fresh real Thomas defects (not already on an evolve/auto-* branch), fix each on its own branch, verify, append to the morning report. Propose-only.',
  phases: [
    { title: 'Discover', detail: 'find fresh defects, skipping ones already branched' },
    { title: 'Fix', detail: 'worktree-isolated reproduce -> fix -> verify -> commit-to-branch' },
    { title: 'Report', detail: 'append to the running review queue' },
  ],
}

const ROOT = 'C:\\Users\\corbe\\Thomas'

const RULES =
  `You are running UNATTENDED while Calvin sleeps. Absolute rules:\n` +
  `- You are in your OWN isolated git worktree (a separate copy of ${ROOT}). Work only there.\n` +
  `- PROPOSE-ONLY: commit your fix to a NEW branch evolve/auto-<id>. NEVER merge/push to dev or main. NEVER 'thomas ship'.\n` +
  `- Do NOT edit any file under [protected_files] in agent_safety.toml. If your fix needs one: status='deferred'.\n` +
  `- NEVER --no-verify, NEVER drive breakglass / THOMAS_SKIP_BREAKGLASS. If a gate blocks needing human approval: status='deferred' with the gate name + full diff in summary.\n` +
  `- TEST-FIRST where feasible (red->green); run the relevant tests + 'ruff check' on changed files; tag commits 'Thomas-Agent: claude'; retry a transient gate failure ONCE.\n` +
  `- No claim without proof. If you cannot verifiably improve it: status='failed', do not commit a half-fix.\n`

const CYCLE = {
  type: 'object',
  properties: {
    id: { type: 'string' }, title: { type: 'string' },
    status: { type: 'string', enum: ['fixed', 'deferred', 'failed'] },
    verified: { type: 'boolean' }, branch: { type: 'string' },
    proof: { type: 'string' }, files: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
  },
  required: ['id', 'title', 'status', 'verified', 'branch', 'proof', 'summary'],
}

phase('Discover')
const discovery = await agent(
  `Find 6 FRESH, concrete, fixable defects in the Thomas chat/server/agent/memory code at ${ROOT}. FIRST run ` +
  `\`git branch --list 'evolve/auto-*'\` and skim recent \`git log --oneline -40 --all\` so you do NOT re-pick anything ` +
  `already fixed or already on a branch. Prefer real bugs with a clear repro and a NON-protected fix (logic errors, ` +
  `missing error handling, silent failures, races, wrong defaults, untested edge cases). Avoid anything needing a ` +
  `protected-file edit (gates/breakglass/shell.py/rules_of_road/skills_*) or a Calvin tap. For each return ` +
  `{id (short-slug), title, task (precise fix instruction with file paths + a done-signal)}.`,
  { label: 'discover', phase: 'Discover', effort: 'high',
    schema: { type: 'object', properties: { items: { type: 'array', items: {
      type: 'object', properties: { id: { type: 'string' }, title: { type: 'string' }, task: { type: 'string' } },
      required: ['id', 'title', 'task'] } } }, required: ['items'] } }
)
const items = (discovery?.items || []).slice(0, 6)
log(`Discovered ${items.length} fresh defects.`)

phase('Fix')
const results = (await parallel(
  items.map((item) => () =>
    agent(
      `Fix ONE Thomas defect end-to-end, then report.\n\n${RULES}\n\nISSUE [${item.id}] ${item.title}:\n${item.task}\n\n` +
      `Commit to branch evolve/auto-${item.id} if it passes. Return the structured result with real proof.`,
      { label: `fix:${item.id}`, phase: 'Fix', schema: CYCLE, isolation: 'worktree', effort: 'high' }
    )
  )
)).filter(Boolean)

phase('Report')
const report = await agent(
  `APPEND a dated section to Calvin's morning review queue at ${ROOT}\\plans\\thomas\\evolve_auto\\REPORT.md (create the ` +
  `file with a title if it does not exist; use the Read/Write/Edit tools). The new section: a one-line headline, then a ` +
  `table of this round's READY branches (id | fix | verified+proof | branch), a DEFERRED list (what it refused + why), and ` +
  `a FAILED list (honest). Do not delete prior sections — append below them. Keep it plain-English and skimmable. ` +
  `This round's results JSON:\n${JSON.stringify(results, null, 1)}\n\nAfter writing, return a one-line summary.`,
  { label: 'report', phase: 'Report', effort: 'medium' }
)

return { fixed: results.filter((r) => r.status === 'fixed').length, total: results.length, report }
