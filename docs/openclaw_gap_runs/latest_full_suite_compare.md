# Full Agent Comparison Suite (thomas-full-agent-comparison-v1)

- Computed at: `2026-02-21T20:02:15Z`
- Config: `F:\DevHub\Thomas\demo\baselines\agent_comparison_suite.current.json`
- Execution policy: quality_is_king=`True`, cycle_limit_disabled=`True`
- Stop condition: `Continue until no known meaningful gaps remain or user explicitly stops.`

## Ranking

- Head-to-head method: `pairwise vs focus agent; counts any runtime metric where either side has data; excludes metrics where neither side has data`
- Overall suite method: `all applicable runtime metric checks + all applicable catalog contract checks`

- #1 `thomas`: head_to_head `89.198`, overall_suite `100.0`, wins `55`, coverage `98.18%`
- #2 `openclaw`: head_to_head `17.13`, overall_suite `58.224`, wins `0`, coverage `85.45%`
- #3 `aider`: head_to_head `7.87`, overall_suite `13.962`, wins `0`, coverage `50.0%`
- #4 `open_interpreter`: head_to_head `7.407`, overall_suite `13.585`, wins `0`, coverage `50.0%`

## Full Coverage Contract

- Tracked checks: `320` (implemented `320`, planned `0`)
- Runtime metrics tracked: `110` (focus data `108`, comparable `94`)
- Catalog `implemented`: `210`

## Agent Data Health

### thomas
- Root: `F:\DevHub\Thomas`
- Version: `n/a` (up_to_date=unknown)
- Model snapshot: ok=True, day=`2026-02-21`, model=`gemini-1.5-pro-latest`
- Strict checks: 4 passed / 4 total
- Benchmark runs used: 3
- Errors: none

### openclaw
- Root: `F:\DevHub\_tmp_openclaw_count_1771454552`
- Version: `ac633366ce1314253c9a2601aae86daed9c93054` (up_to_date=yes)
- Model snapshot: ok=True, day=`2026-02-21`, model=`runtime-configured`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 3
- Errors: none

### aider
- Root: `F:\DevHub\_tmp_competitor_aider`
- Version: `7afaa26f8b8b7b56146f0674d2a67e795b616b7c` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### open_interpreter
- Root: `F:\DevHub\_tmp_competitor_open_interpreter`
- Version: `681f5ce5b84bc96a2a4cc5e90daa6328f3f796e0` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

## Focus Gaps

- none

## Competitor Pressure

- none

## Prediction Evo Scope

### Predicted Next Competitor Focus
- `general_surface_growth` (1 signals)

### Recommended Thomas Counter-Moves
- Monitor breadth growth and preemptively add targeted strict checks in the fastest-growing directories. (1 signals)
