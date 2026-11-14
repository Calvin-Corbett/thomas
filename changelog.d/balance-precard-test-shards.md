### Fixed

- Apply reviewer cancellation scopes to serial and held-check retries as well as the overlapping path; nested scopes retain the outer cancellation event. Four serial/held regressions fail when that scope is removed and pass with it restored.
- Keep each settle helper within the architecture function-size rule. Restore the repair-ledger suite's real lessons reader after its shared lifecycle fixture substitutes a blank reader.

- Repair the real hand-in clock fixture to use the current green-root and ledger constants, inbox accessor, and proof module; create its isolated green parent folders before cloning.
- Keep lazy-copy clock and checks-off patch-read tests independent of Git repositories. The lazy-copy test still runs two confirmation workers, creates one shared base copy, and checks both worker and parent clocks; the real hand-in test retains its repository fixture.

- Bound both memoization regressions' on-disk trees and selection caps instead of scanning the checkout. One uses real importer sources copied into a temporary tree; the other checks explicit import/helper choices and overflow. Isolate the tiny real-hand-in fixture from the full-checkout size gate; exercise cache eviction with relevant source text.

- Balance parallel proof shards by source-bound timing hints, falling back to test-definition counts, instead of consecutive twelve-file groups. Preserve every selected file, the per-shard file limit, serial grouping, pool capacity, and failure confirmation. Do not learn a duration against bytes rewritten during that shard.
- Record changed-copy and fallback dev-copy shard files and elapsed times, plus shared-pool wait and run seconds, in the existing hand-in clocks. Preserve selection results and the independent second look.
- Keep the parallel second look's clock in the hand-in record, reuse its verdict when checks are explicitly off, and leave unreadable patch snapshots to the check's normal hold/retry handling.
- Cancel the parallel second look when a failed check cannot use its verdict. Preserve dev's direct ChatGPT reviewer and changed-file prompt context, cancelling the pending request through the review scope and retaining the legacy `second_look_cli` execution clock. The retained subprocess helper uses file-backed prompt/output, Windows job containment, and POSIX process-group cleanup; passing checks still require the second look.
- Skip irrelevant ASCII test-source parsing during selection, retaining conservative Unicode parsing and transitive imports through helpers and test modules, including relative imports. A same-checkout rerun selected identical files in 42.279 seconds before and 5.539 seconds after.
- Submit heavier completed groups first and avoid extra shard waves for small selections, keeping the per-shard file limit. Spread zero-duration hints across available workers rather than concentrating them in the first group.
- Require every selected file to appear in its shard report, including named-file collection. Treat skipped or unfinished confirmations as inconclusive, and resolve inherited tests to their collected module and class before confirming a failure.
- A local four-file comparison collected 40 tests in both runs: 337.725 seconds with consecutive grouping and 106.901 seconds with balancing. Both reported the same failure, reproduced separately on unchanged dev. This is a measured test-run improvement, not a full-card latency guarantee; see `docs/PRECARD_CHECK_LATENCY.md`.
