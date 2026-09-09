// Renders the real runReportHtml against one report per KIND of run and prints
// the markup each one produces, so the python test can assert on the words a
// person actually reads.
//
//   conversation -- an answer, no build: today's audit measured it wearing a
//                   full build-verification scorecard with manufactured risks
//   stopped      -- the person ended it: measured reading "Nothing was checked
//                   · 1 requirement unverified · 2 open risks", grading a run
//                   nobody let finish
//   unverified   -- the Nova shape: checks passed, ask not separately checked;
//                   measured as the self-contradicting pair "Not checked
//                   against your ask" directly above "2/2 checks passed"
//   verified     -- the control: a run that really checked its requirements
//                   must keep its plain green
//
// Prints JSON: { "<name>": "<html>", ... }
import fs from 'node:fs';
import vm from 'node:vm';

globalThis.window = {};
const sourcePath = process.argv[2];
vm.runInThisContext(fs.readFileSync(sourcePath, 'utf8'), { filename: sourcePath });
const api = window.ThomasCodeResults;
api.configure({
  state: { activeId: 'test' },
  esc: value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;'),
  isInternalResultPath: () => false,
  lifecycle: () => ({}),
  render: () => {},
});

const passingChecks = [
  {
    kind: 'engine_check',
    command: 'static checks: syntax + parse + open (index.html)',
    passed: true,
    evidence: 'exit 0 parsed index.html STATIC_VERIFY_OK: 1 files checked',
  },
  {
    kind: 'engine_check',
    command: 'offline real-browser smoke for changed HTML',
    passed: true,
    evidence: 'BROWSER_SMOKE_OK: index.html: browser boot clean; boot only',
  },
];
const unverifiedRubric = [
  { criterion: 'the run finished without error', status: 'met', evidence: 'outcome=completed' },
  {
    criterion: 'the specific requirements stated in this goal',
    status: 'unverified',
    evidence: 'the goal was not written as a checklist',
  },
];

const fixtures = {
  // The explain-only run from the audit, verbatim in shape: a final reply, no
  // changed files, and two risks that trace to the harness, not the run.
  conversation: {
    outcome: 'conversation',
    attempts: [{ pass: 1, goal: 'what does this project do?', outcome: 'conversation', exit_state: 'exit 1' }],
    validations: [],
    open_risks: [
      { risk: 'run exited non-zero (1)', detail: 'Thomas replied without changing files' },
      { risk: 'error surfaced during the run', detail: 'claude reported an error' },
    ],
    rubric_mapping: unverifiedRubric,
  },
  stopped: {
    outcome: 'stopped',
    attempts: [{ pass: 1, goal: 'build me a ledger', outcome: 'stopped', exit_state: 'exit -15 — stopped by you' }],
    validations: [],
    open_risks: [
      { risk: 'run exited non-zero (-15)', detail: 'stopped by you' },
      { risk: 'changed files were never validated', detail: '1 file(s) changed but no engine check ran' },
    ],
    rubric_mapping: [
      { criterion: 'the specific requirements stated in this goal', status: 'unverified', evidence: 'stopped' },
    ],
  },
  unverified: {
    outcome: 'completed',
    attempts: [{ pass: 1, goal: 'build me the future of calculator apps', outcome: 'completed', exit_state: 'exit 0' }],
    validations: passingChecks,
    open_risks: [],
    rubric_mapping: unverifiedRubric,
  },
  verified: {
    outcome: 'completed',
    attempts: [{ pass: 1, goal: 'g', outcome: 'completed', exit_state: 'exit 0' }],
    validations: [passingChecks[0]],
    open_risks: [],
    rubric_mapping: [{ criterion: 'counts down from 10', status: 'met', evidence: 'asserted' }],
  },
};

const out = {};
for (const [name, report] of Object.entries(fixtures)) out[name] = api.runReportHtml(report);
process.stdout.write(JSON.stringify(out));
