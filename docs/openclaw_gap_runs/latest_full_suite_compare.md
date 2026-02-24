# Full Agent Comparison Suite (thomas-full-agent-comparison-v1)

- Computed at: `2026-02-21T21:56:46Z`
- Config: `F:\DevHub\Thomas\demo\baselines\agent_comparison_suite.current.json`
- Execution policy: quality_is_king=`True`, cycle_limit_disabled=`True`
- Stop condition: `Continue until no known meaningful gaps remain or user explicitly stops.`

## Ranking

- Head-to-head method: `explicit 1v1 pair; counts runtime metrics where either side has data; excludes metrics where neither side has data; tie handling follows suite head_to_head_tie_policy`
- Token efficiency method: `token-aware blended score using effective tokens per success, token telemetry coverage, success quality, and cost probe reliability`
- Overall suite method: `all applicable runtime metric checks + all applicable catalog contract checks`
- Lane suite method: `quick/dynamic/human suite scores use the same formula but only checks tagged to that mode`
- Score math:
- runtime head_to_head: `winner=1`, `ties_excluded`, `score=(points/counted_metrics)*100`
- head_to_head_decisive: `winner=1`, `ties_excluded`, `score=(wins/non_tied_counted)*100`
- overall_suite: `(runtime_passed + catalog_passed) / (runtime_applicable + catalog_applicable) * 100`
- lane_suite_scores: same formula as overall, filtered by `test_mode` (`quick`, `dynamic`, `human`)
- token_efficiency: separate token-only scoring block, emitted only with token telemetry evidence

- #1 `thomas`: overall_suite `100.0`, capability `75.689`, quick_suite `100.0`, dynamic_suite `100.0`, human_suite `0.0`, runtime_rank `1`, head_to_head `100.0`, decisive_h2h `100.0`, token_efficiency `n/a`, verdict `LIMITED_GO`, runtime_wins `55`, runtime_coverage `96.52%`
- #2 `openclaw`: overall_suite `55.452`, capability `42.725`, quick_suite `62.5`, dynamic_suite `51.244`, human_suite `0.0`, runtime_rank `2`, head_to_head `0.0`, decisive_h2h `0.0`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `84.35%`
- #3 `gpt_engineer`: overall_suite `29.078`, capability `18.83`, quick_suite `27.778`, dynamic_suite `29.688`, human_suite `0.0`, runtime_rank `5`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #4 `aider`: overall_suite `13.475`, capability `7.96`, quick_suite `3.333`, dynamic_suite `18.229`, human_suite `0.0`, runtime_rank `6`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #5 `swe_agent`: overall_suite `13.475`, capability `7.96`, quick_suite `3.333`, dynamic_suite `18.229`, human_suite `0.0`, runtime_rank `13`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #6 `open_interpreter`: overall_suite `13.121`, capability `7.847`, quick_suite `4.444`, dynamic_suite `17.188`, human_suite `0.0`, runtime_rank `14`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #7 `cline`: overall_suite `13.121`, capability `7.847`, quick_suite `4.444`, dynamic_suite `17.188`, human_suite `0.0`, runtime_rank `7`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #8 `roo_code`: overall_suite `13.121`, capability `7.847`, quick_suite `4.444`, dynamic_suite `17.188`, human_suite `0.0`, runtime_rank `11`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #9 `continue`: overall_suite `13.121`, capability `7.847`, quick_suite `4.444`, dynamic_suite `17.188`, human_suite `0.0`, runtime_rank `8`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #10 `crewai`: overall_suite `13.121`, capability `7.847`, quick_suite `4.444`, dynamic_suite `17.188`, human_suite `0.0`, runtime_rank `4`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #11 `openhands`: overall_suite `12.766`, capability `7.555`, quick_suite `3.333`, dynamic_suite `17.188`, human_suite `0.0`, runtime_rank `12`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #12 `autogpt`: overall_suite `12.766`, capability `7.555`, quick_suite `3.333`, dynamic_suite `17.188`, human_suite `0.0`, runtime_rank `3`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #13 `autogen`: overall_suite `12.766`, capability `7.555`, quick_suite `3.333`, dynamic_suite `17.188`, human_suite `0.0`, runtime_rank `10`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #14 `langgraph`: overall_suite `12.766`, capability `7.555`, quick_suite `3.333`, dynamic_suite `17.188`, human_suite `0.0`, runtime_rank `9`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`

## Head-to-Head (1v1)

- Pair: `thomas` vs `openclaw`
- Scores: `thomas`=`100.0`, `openclaw`=`0.0` (tie_policy `exclude`, counted_metrics `73`, ties_counted `0`, ties_observed `38`)
- Decisive (ties excluded): `thomas`=`100.0`, `openclaw`=`0.0` (counted_metrics `73`)
- By mode `quick`: `thomas`=`100.0`, `openclaw`=`0.0` (counted_metrics `45`, ties_counted `0`, ties_observed `15`)
- By mode `dynamic`: `thomas`=`100.0`, `openclaw`=`0.0` (counted_metrics `28`, ties_counted `0`, ties_observed `23`)

## Token Efficiency

- Method: `1v1 uses token_efficiency_score, effective_tokens_per_success, and telemetry_coverage; overall ranks by token_efficiency_score`
- Pair: `thomas` vs `openclaw`
- Scores: `thomas`=`None`, `openclaw`=`None` (counted_metrics `0`, ties `0`)
- `#1` `thomas`: score `None`, tokens_per_success `None`, coverage `0.0`
- `#2` `openclaw`: score `None`, tokens_per_success `None`, coverage `0.0`
- `#3` `aider`: score `None`, tokens_per_success `None`, coverage `0.0`
- `#4` `open_interpreter`: score `None`, tokens_per_success `None`, coverage `0.0`
- `#5` `openhands`: score `None`, tokens_per_success `None`, coverage `0.0`
- `#6` `cline`: score `None`, tokens_per_success `None`, coverage `0.0`

## Benchmark Program

- Program id: `thomas-professional-benchmark-v2`
- Lane weight `dynamic`: `0.5`
- Lane weight `human`: `0.15`
- Lane weight `quick`: `0.35`
- Verdict `LIMITED_GO`: `1`
- Verdict `NO_GO`: `13`
- `#1` `thomas`: capability `75.689`, quick `100.0`, dynamic `81.377`, verdict `LIMITED_GO`
- `#2` `openclaw`: capability `42.725`, quick `62.5`, dynamic `41.7`, verdict `NO_GO`
- `#3` `gpt_engineer`: capability `18.83`, quick `20.833`, dynamic `23.077`, verdict `NO_GO`
- `#4` `aider`: capability `7.96`, quick `2.5`, dynamic `14.17`, verdict `NO_GO`
- `#5` `swe_agent`: capability `7.96`, quick `2.5`, dynamic `14.17`, verdict `NO_GO`
- `#6` `open_interpreter`: capability `7.847`, quick `3.333`, dynamic `13.36`, verdict `NO_GO`
- `#7` `cline`: capability `7.847`, quick `3.333`, dynamic `13.36`, verdict `NO_GO`
- `#8` `roo_code`: capability `7.847`, quick `3.333`, dynamic `13.36`, verdict `NO_GO`

## Full Coverage Contract

- Tracked checks: `370` (implemented `370`, planned `0`)
- Runtime metrics tracked: `115` (focus data `111`, comparable `97`)
- Catalog `implemented`: `255`

## Agent Data Health

### thomas
- Root: `F:\DevHub\Thomas`
- Version: `e7a4e3f6ed03834ceae0bee35a9aa7c102699cf3` (up_to_date=unknown)
- Model snapshot: ok=True, day=`2026-02-21`, model=`gemini-1.5-pro-latest`
- Strict checks: 4 passed / 4 total
- Benchmark runs used: 3
- Errors:
  - git remote head query failed: fatal: ambiguous argument 'origin/main': unknown revision or path not in the working tree.

### openclaw
- Root: `F:\DevHub\_tmp_openclaw_count_1771454552`
- Version: `861718e4dcbd33354b87b84bf5df8c9d92d21307` (up_to_date=yes)
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

### openhands
- Root: `F:\DevHub\_tmp_competitor_openhands`
- Version: `872f2b87f20ccb7e62ebe716deeb43d8e1082361` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### cline
- Root: `F:\DevHub\_tmp_competitor_cline`
- Version: `03ab2968a643551980eb755cc2c9ec817db83a9b` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### roo_code
- Root: `F:\DevHub\_tmp_competitor_roo_code`
- Version: `62a7bd73547ae6f58d95ba76e2822a0374a21984` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### continue
- Root: `F:\DevHub\_tmp_competitor_continue`
- Version: `a2c1fe6897728ffc78ef5e20660c3a5feefcdb44` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### swe_agent
- Root: `F:\DevHub\_tmp_competitor_swe_agent`
- Version: `39e2931a81c8698265e2db40ec4f3911b630d942` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### gpt_engineer
- Root: `F:\DevHub\_tmp_competitor_gpt_engineer`
- Version: `a90fcd543eedcc0ff2c34561bc0785d2ba83c47e` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### autogpt
- Root: `F:\DevHub\_tmp_competitor_autogpt`
- Version: `062fe1aa709217136b896c8b950e0f04435afb32` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### autogen
- Root: `F:\DevHub\_tmp_competitor_autogen`
- Version: `13e144e5476a76ca0d76bf4f07a6401d133a03ed` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### crewai
- Root: `F:\DevHub\_tmp_competitor_crewai`
- Version: `51754899a2b3e35d94f225bef82cb2957cb1d2b3` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### langgraph
- Root: `F:\DevHub\_tmp_competitor_langgraph`
- Version: `f702729e04dd51b843d257a58f9f5b0181f0be2f` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-02-21`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

## Focus Gaps

- none

## Competitor Pressure

- none

## Prediction Evo Scope

- No competitor delta history yet.

