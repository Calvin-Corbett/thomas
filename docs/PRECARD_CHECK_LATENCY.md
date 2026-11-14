# Pre-card check latency: shard balance

## Measurement

Measured in this checkout on Windows against dev
`4b4963bbe1c55712e3e6d9df8999f8cbb73f1c16`.

A local harness archived HEAD into two scratch trees and ran the same four
shared-card test files through `proof.runner.run_tests`, with four workers,
folder collection, strict reports, and required test cases. The consecutive
schedule was run first, then the balanced schedule; this was not a randomized
or isolated-machine benchmark.

| Work | Measured wall time |
| --- | ---: |
| Archive and extract two tracked-tree copies | 71.766 s |
| Select tests for one shared-card source change | 27.177 s |
| Consecutive schedule, four files in one shard | 337.725 s |
| Balanced schedule, four one-file shards | 106.901 s |

The selection probe returned one file; the execution comparison explicitly
used these four files, rather than implying selection returned four:

- `tests/test_a_shared_card_forms_from_what_can_share.py`
- `tests/test_a_shared_card_lands_nothing_that_changed_under_it.py`
- `tests/test_a_shared_card_records_only_what_happened.py`
- `tests/test_a_shared_card_survives_a_withdrawal_or_a_crash.py`

Both schedules saw 40 test cases and reported the same single failing test,
`test_a_running_copy_that_cannot_be_updated_asks_each_alone`. Running that test
alone also failed on the unchanged HEAD scratch copy and on the changed tree.
This is a timing comparison with equivalent reported coverage and failures,
not a claim that those shared-card tests pass.

The old shard took 337.706 s. The new shards took 67.463 s, 67.562 s,
102.263 s, and 106.882 s. The measured execution phase fell by 68.3%, or
3.16 times. Three worker lanes had no shard to execute in the old schedule;
the new schedule gave each lane one. These runs used the runner directly,
not the machine-wide admission ledger, so they do not measure admission or
pool contention. Copying was measured with archive/extraction rather than
claiming it was the production `green_checkout.create` path.

A repeat of the four-file runner comparison under different machine load took
551.237 s with consecutive grouping and 245.552 s with balancing, again with
40 cases and the same failure. The large variation is why these numbers are
phase comparisons, not an end-to-end percentile for a typical hand-in.

A separate selection of the tests covering the three initially changed runtime
modules returned 35 files in 8.819 s. The selection optimization below was
measured separately; those phases were not a single end-to-end check.

A repeat under heavier concurrent load measured 33.273 s for two archived
copies, 57.641 s for selection before the selection optimization, and 551.237 s
versus 245.552 s for the same consecutive/balanced comparison. Both runs again
reported 40 cases and the same failure. The absolute times vary with machine
load; balancing improved this repeat's execution phase by 55.5%.

A separate cold-selection comparison loaded unchanged dev's selector and the
new selector against the same checkout and source path. Both returned exactly
`tests/test_architecture.py` with no omitted files. Parsing fell from 1,984 to
522 source texts and elapsed time from 12.255 s to 5.743 s (53.1%). The negative
filter only avoids AST parsing when an ASCII source cannot name any relevant
module leaf. Unicode source is still parsed, preserving Python identifier
normalization. Helper propagation, import/string matching, ranking, caps and
the selected-file set are unchanged; regressions compare lazy and eager paths.
A resumed-pass comparison over the three initially changed runtime paths read
the test sources once and returned identical 37-file results and overflow:
12.883 s with dev's eager selector and 7.783 s with the optimized selector.

## Change

Parallel runs now order files by estimated cost and distribute them across
cost-balanced shards. The initial number of shards is the larger of the worker
count and the number needed to respect the existing per-shard file limit,
bounded by the number of selected files. Assigned groups are submitted
heaviest first. This avoids extra pytest startups for small selections while
starting expensive groups early. A file is never split or omitted. Serial
runs and one-file shard requests retain consecutive grouping.

The cold estimate counts test definitions, not collected parameterized cases.
Completed shard JUnit reports provide per-file case durations for subsequent
scheduling in this process. Hints are keyed by relative path and source hash,
so identical copies can share them, and edited bytes cannot inherit the old
hint. The runner fingerprints each shard's sources before execution and skips
learning a file's duration if its bytes changed during execution. The cache is
bounded to 4,096 entries. Estimates are not test evidence,
are not persisted across restarts, and cannot remove a selected test.

`precard.check` records ordered `change_shards` and, when used, `dev_shards`
observations alongside its existing clocks. For shared-pool runs it also records
aggregate `pool_wait_s` and `pool_run_s` after the changed-tree run, baseline
fallback and failure confirmation. Shard elapsed time includes the runner
call, including any pool wait; it is not presented as pure CPU time. Aggregate
pool seconds can exceed wall time when workers overlap.

The existing clock record separates admission (`slot_wait`), copy creation
(`change_copy` and, when needed, `base_copy`), admission selection (`pick_tests`),
authoritative selection (`selection`), changed-tree tests (`change_run`), failure
confirmation (`confirm_failures`), and the independent review (`second_look`).
The independent review still decides the hand-in through the existing verdict
path. Its worker now inherits the clock context, and an explicitly disabled
check reuses the already completed parallel verdict rather than requesting a
second review. No live independent-model review latency was measured by the
local runner benchmark.

The selection rules, pool capacity, isolation, strict report checks, baseline
fallback, and failure confirmations remain in place. Slow individual files can
still dominate; the scheduler does not promise a two-minute end-to-end check.

## Focused hand-in after the steering update

No earlier `precard-resume` background process remained when this pass checked
process command lines. This pass did not launch another broad background sweep.
It used sequential `check.run` calls, each naming at most 15 test files.

The deleted-helper regressions cover bare `import support`, absolute and relative
imports, transitive consumers, and overflow reporting. An on-disk case omits the
deleted helper entirely. Removing the changed-helper seed in a disposable copy
made its three on-disk cases fail; the working selector was not modified by that
mutation.

The resumed done-check also covers nested test directories exposed directly on
Python's import path and conventional `src/` production layouts. Removing nested
helper aliases in a disposable selector fails 36 parameterized regression cases;
removing `src/` aliases fails 12. Restored code passes both suites. Deleted paths
and cap overflow remain covered. The sequential focused batches passed 379 tests
with one skip; Ruff check passed and format reported 41 files already formatted.
These are development verification results, not a live end-to-end latency sample.

The final focused batches covered every changed test file plus architecture:
175 passed in 472.83 seconds, 133 passed in 184.47 seconds, and 35 passed with
one skip in 45.82 seconds. These are development verification times, not a
full-card speedup measurement. Ruff check passed and Ruff format reported
41 files already formatted. The monolith guard reported no violations; a
separate changed-file check verified growth against local `dev`. The tracked
patch applied in a disposable index at local `dev`
`4b4963bbe1c55712e3e6d9df8999f8cbb73f1c16`, with no new-path collisions.

## Restart repair: bounded selection regression

The repeated three-file verification measured 338.09 seconds under load and
101.74 seconds on a repeat before this repair. The repeat spent 54.72 seconds
in the two whole-checkout memoization comparisons. Those comparisons now use a
bounded on-disk tree with direct imports, transitive helpers, unrelated files,
Unicode identifiers, invalid syntax, and selection overflow at an explicit
small cap. Both cold and warm results are checked against expected paths; the
warm pass must perform no AST parsing. The eviction regression now uses import
text that exercises the memo rather than being rejected by the negative filter.

After the repair, the exact three-file verification passed all 46 tests in
98.45 seconds; the resumed pass repeated it with 46 passing in 103.78 seconds.
These are regression-check measurements, not new full-card latency measurements.
Host load and test-session setup remain outside that bound.

The resumed pass also ran the test files directly importing the changed proof/check
modules, restart-support callers, and `tests/test_architecture.py`: 426 passed in
1389.62 seconds. A later serial regression passed 579 tests in 1308.50 seconds.
The final 53-file regression was divided among four processes: 166 passed in
663.21 seconds, 137 passed in 503.12 seconds, 131 passed in 820.69 seconds, and
152 passed with one platform skip in 764.63 seconds (586 passed in total).
The new normal-completion process-group test passed separately with the reviewer
suite. These broad development sweeps are not a typical hand-in's selected
proof set. The final focused run of all changed test files plus architecture
passed 110 tests with one platform skip in 276.90 seconds.

## Five-file timeout repair

The resumed five-file verifier passed 42 cases in 75.37 seconds on its first
run, but a repeat exceeded 150 seconds after printing all 42 progress markers.
A later diagnostic run passed in 94.26 seconds; its lazy-copy clock case spent
21.48 seconds creating repository fixtures despite substituting the proof run.
That case and the two checks-off read-error cases now use an isolated Green
value and patch repository boundaries, rather than initializing and cloning Git
repositories. The real hand-in clock case still uses its repository fixture.
The same five-file verifier then passed all 42 cases in 46.96 seconds. A repeat
while the broader regression run was active passed in 73.18 seconds.

Temporarily removing context propagation from lazy base-copy creation made the
reworked clock case fail because `base_copy` was absent from its stage record.
Temporarily restoring consecutive runner batches made the shard integration
case fail on the observed selected-file groups. Both changes were restored.

## Reviewer cleanup

The parallel reviewer receives the clock context and a cancellation event. A
failed check cancels its reviewer; a passing check still requires its verdict.
The merged pre-card reviewer now calls ChatGPT directly and polls the review
cancellation event while the request is pending. Its execution stage retains
the legacy `second_look_cli` name; admission still has a separate clock.
The retained subprocess runner uses temporary files for prompt and output,
so neither a blocked stdin write nor inherited output pipes hold up cleanup.
Windows job containment reaps descendants when the launcher exits. POSIX
reviewers start a separate session and stop their process group on cancellation
and normal completion. A platform-independent process-double regression failed
before normal-completion group cleanup was added; the restored reviewer suites
passed 12 tests with one platform skip on Windows in 73.91 seconds.

## Continuation verification

A fresh real-hand-in fixture completed in 17.750 seconds, with copies at
0.688 seconds, initial selection at 0.078 seconds, slot wait at 0.125 seconds,
shared-pool wait at 0.251 seconds, changed-copy testing at 3.781 seconds,
confirmation at 0.063 seconds, and the substituted reviewer at 0.063 seconds.
The fixture's second look is not a live provider call; this measurement proves
stage recording and overlap, not a typical production reviewer duration. Its
pytest session passed in 51.28 seconds.

Serial second looks, including held-check retries, now enter the same reviewer
job context as parallel second looks. Nested contexts retain the outer
cancellation event. Removing the serial context made all four serial/held
success/timeout cases fail; restoring it passed those cases. The final focused
run, including architecture and settle-name checks, passed 46 tests with one
Windows platform skip in 106.84 seconds.

The broader regression exposed a shared fixture that replaces the repair-ledger
lesson reader with an empty stub. The ledger-specific fixture now restores the
real reader, so its assertions exercise the ledger rather than that stub.
The settle path again delegates its held/parallel decision to `_checked_with_review`,
keeping `settle_if_finished` within the 100-line function limit.

## Regression checks

The shard tests verify selected-path multiplicity, bounds, serial grouping,
source-bound timing hints, and preservation of runner failures and case counts.
Disposable substitutions of consecutive scheduling, extra-wave sizing, and
insertion-order submission failed their corresponding regressions. Removing
the new pool/shard clock observations failed the check-clock regression.
Restoring eager selection parsing failed the new irrelevant-parsing regression;
the other selection cases still matched the eager results. The restored shard
and selection regression suites passed all 36 cases.

## Resumed verification

A cold selection comparison in the same checkout selected exactly the same file
and no overflow in both versions: 42.279 seconds and 1,997 parsed sources before,
5.539 seconds and 550 parsed sources after. These are local selection timings,
not a live card's total elapsed time.

A subsequent four-file runner comparison retained all 40 cases and the same
failure in both layouts. Consecutive scheduling took 839.840 seconds; balanced
scheduling took 322.920 seconds, with individual shards taking 186.077,
193.626, 312.300 and 322.813 seconds. The assertion about a running copy's clean
state failed in both runs; this is a timing comparison with equal coverage and
outcomes, not evidence of a passing proof. The two archive copies took 127.736
seconds. The machine was also running regression checks, so these numbers do
not establish an uncontended production latency target.

The resumed direct affected run passed 645 tests with one skip across 61 files.
A focused confirmation, selection, cost-hint and missing-file run passed 62 tests;
architecture passed 13 tests. Disposable removal of inherited-node identity,
transitive test-module propagation and zero-cost shard spreading failed two,
four and one regression cases respectively; the restored focused run passed.
Inherited methods use the collecting module and class for confirmation, and
missing selected files hold named-file runs as well as folder runs.

## Conftest import coverage repair

The resumed focused checks exposed a remaining coverage gap: `conftest.py` was
excluded from explicit import propagation, despite being importable outside its
fixture scope. Selection now seeds deleted conftests and follows conftests reached
through production dependencies or asset references. The existing fixture-scope
selection remains in place.

Sequential `check.run` batches, each containing at most 12 test files, passed
191, 134, 117, 124 and 65 tests respectively; the last batch also skipped one
test. The first batch includes architecture. Restoring both conftest exclusions
in a disposable selector failed all three targeted probes; the intact selector
passed the same three probes. Ruff check passed and format check reported
`41 files already formatted`. The size gate reported no violations; all 41
changed Python files parsed and remained below 800 lines.

These focused checks do not measure a typical live card's end-to-end latency.
The copy, selection and runner comparisons above remain component measurements;
production pool waiting and independent-review latency still need live evidence.
