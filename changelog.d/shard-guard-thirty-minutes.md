### Fixed
- A slow but working batch of tests no longer fails a check before your card. A shard of tests may now run for 30 minutes inside the check's hour instead of 15: the four shared-card test files take about four minutes each and sort into one shard, so every check that selected them ran out of time on dev too and was held (2026-10-23).
