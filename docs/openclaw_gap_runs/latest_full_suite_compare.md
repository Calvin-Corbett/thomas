# Full Agent Comparison Suite (thomas-full-agent-comparison-v1)

- Computed at: `2026-03-06T13:11:26Z`
- Config: `C:\Users\corbe\Thomas\demo\baselines\agent_comparison_suite.current.json`
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

- #1 `thomas`: overall_suite `99.407`, capability `85.51`, quick_suite `98.333`, dynamic_suite `100.0`, human_suite `0.0`, runtime_rank `1`, head_to_head `98.684`, decisive_h2h `98.684`, token_efficiency `75.159602`, verdict `GO`, runtime_wins `54`, runtime_coverage `98.26%`
- #2 `openclaw`: overall_suite `55.452`, capability `42.815`, quick_suite `63.333`, dynamic_suite `50.746`, human_suite `0.0`, runtime_rank `2`, head_to_head `1.316`, decisive_h2h `1.316`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `1`, runtime_coverage `84.35%`
- #3 `gpt_engineer`: overall_suite `28.723`, capability `18.628`, quick_suite `27.778`, dynamic_suite `29.167`, human_suite `0.0`, runtime_rank `5`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #4 `crewai`: overall_suite `13.83`, capability `8.341`, quick_suite `5.556`, dynamic_suite `17.708`, human_suite `0.0`, runtime_rank `3`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `1`, runtime_coverage `50.43%`
- #5 `open_interpreter`: overall_suite `13.475`, capability `8.049`, quick_suite `4.444`, dynamic_suite `17.708`, human_suite `0.0`, runtime_rank `14`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #6 `aider`: overall_suite `13.121`, capability `7.758`, quick_suite `3.333`, dynamic_suite `17.708`, human_suite `0.0`, runtime_rank `8`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #7 `swe_agent`: overall_suite `13.121`, capability `7.758`, quick_suite `3.333`, dynamic_suite `17.708`, human_suite `0.0`, runtime_rank `13`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #8 `autogen`: overall_suite `13.121`, capability `7.758`, quick_suite `3.333`, dynamic_suite `17.708`, human_suite `0.0`, runtime_rank `7`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #9 `langgraph`: overall_suite `13.121`, capability `7.758`, quick_suite `3.333`, dynamic_suite `17.708`, human_suite `0.0`, runtime_rank `9`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #10 `cline`: overall_suite `12.766`, capability `7.644`, quick_suite `4.444`, dynamic_suite `16.667`, human_suite `0.0`, runtime_rank `12`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #11 `roo_code`: overall_suite `12.766`, capability `7.644`, quick_suite `4.444`, dynamic_suite `16.667`, human_suite `0.0`, runtime_rank `11`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #12 `continue`: overall_suite `12.766`, capability `7.644`, quick_suite `4.444`, dynamic_suite `16.667`, human_suite `0.0`, runtime_rank `10`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #13 `openhands`: overall_suite `12.411`, capability `7.353`, quick_suite `3.333`, dynamic_suite `16.667`, human_suite `0.0`, runtime_rank `6`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`
- #14 `autogpt`: overall_suite `12.411`, capability `7.353`, quick_suite `3.333`, dynamic_suite `16.667`, human_suite `0.0`, runtime_rank `4`, head_to_head `n/a`, decisive_h2h `n/a`, token_efficiency `n/a`, verdict `NO_GO`, runtime_wins `0`, runtime_coverage `50.43%`

## Head-to-Head (1v1)

- Pair: `thomas` vs `openclaw`
- Scores: `thomas`=`98.684`, `openclaw`=`1.316` (tie_policy `exclude`, counted_metrics `76`, ties_counted `0`, ties_observed `37`)
- Decisive (ties excluded): `thomas`=`98.684`, `openclaw`=`1.316` (counted_metrics `76`)
- By mode `quick`: `thomas`=`97.778`, `openclaw`=`2.222` (counted_metrics `45`, ties_counted `0`, ties_observed `15`)
- By mode `dynamic`: `thomas`=`100.0`, `openclaw`=`0.0` (counted_metrics `31`, ties_counted `0`, ties_observed `22`)

## Token Efficiency

- Method: `1v1 uses token_efficiency_score, effective_tokens_per_success, and telemetry_coverage; overall ranks by token_efficiency_score`
- Pair: `thomas` vs `openclaw`
- Scores: `thomas`=`100.0`, `openclaw`=`0.0` (counted_metrics `3`, ties `0`)
- `#1` `thomas`: score `75.159602`, tokens_per_success `52.0`, coverage `0.75`
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
- Verdict `GO`: `1`
- Verdict `NO_GO`: `13`
- `#1` `thomas`: capability `85.51`, quick `98.333`, dynamic `82.186`, verdict `GO`
- `#2` `openclaw`: capability `42.815`, quick `63.333`, dynamic `41.296`, verdict `NO_GO`
- `#3` `gpt_engineer`: capability `18.628`, quick `20.833`, dynamic `22.672`, verdict `NO_GO`
- `#4` `crewai`: capability `8.341`, quick `4.167`, dynamic `13.765`, verdict `NO_GO`
- `#5` `open_interpreter`: capability `8.049`, quick `3.333`, dynamic `13.765`, verdict `NO_GO`
- `#6` `aider`: capability `7.758`, quick `2.5`, dynamic `13.765`, verdict `NO_GO`
- `#7` `swe_agent`: capability `7.758`, quick `2.5`, dynamic `13.765`, verdict `NO_GO`
- `#8` `autogen`: capability `7.758`, quick `2.5`, dynamic `13.765`, verdict `NO_GO`

## Full Coverage Contract

- Tracked checks: `370` (implemented `370`, planned `0`)
- Runtime metrics tracked: `115` (focus data `113`, comparable `97`)
- Catalog `implemented`: `255`

## Agent Data Health

### thomas
- Root: `C:\Users\corbe\Thomas`
- Version: `e55f2b7de47b588658983f314110018b96a3b98e` (up_to_date=unknown)
- Model snapshot: ok=True, day=`2026-03-06`, model=`gpt-5.3-codex`
- Strict checks: 4 passed / 4 total
- Benchmark runs used: 3
- Errors:
  - git remote head query failed: fatal: ambiguous argument 'origin/main': unknown revision or path not in the working tree.

### openclaw
- Root: `F:\DevHub\_tmp_openclaw_latest_20260306`
- Version: `fa6c0e1b404f094e579b5fb192c6643c7822c1b6` (up_to_date=yes)
- Model snapshot: ok=True, day=`2026-03-06`, model=`runtime-configured`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 3
- Errors: none

### aider
- Root: `F:\DevHub\_tmp_competitor_aider`
- Version: `265d8a473b5d5bf001db321b251674a120ad75da` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### open_interpreter
- Root: `F:\DevHub\_tmp_competitor_open_interpreter`
- Version: `681f5ce5b84bc96a2a4cc5e90daa6328f3f796e0` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### openhands
- Root: `F:\DevHub\_tmp_competitor_openhands`
- Version: `1f1fb5a95438c1d672ec2cbf0d1ce400fb57e5e0` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### cline
- Root: `F:\DevHub\_tmp_competitor_cline`
- Version: `a562868cb90039afc0b6ac80e82e6554f3c7d90e` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### roo_code
- Root: `F:\DevHub\_tmp_competitor_roo_code`
- Version: `0892455db298ef5b48e8153a8e3d11763b5b4584` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### continue
- Root: `F:\DevHub\_tmp_competitor_continue`
- Version: `6bd9618dd98d2092897e3e1257fce46257820e3e` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### swe_agent
- Root: `F:\DevHub\_tmp_competitor_swe_agent`
- Version: `21b5a6a453ce6052f44e7403a33ba8ded6e80bd8` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### gpt_engineer
- Root: `F:\DevHub\_tmp_competitor_gpt_engineer`
- Version: `a90fcd543eedcc0ff2c34561bc0785d2ba83c47e` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### autogpt
- Root: `F:\DevHub\_tmp_competitor_autogpt`
- Version: `3e108a813a9c31f0f13168fc26afc0d1d878dbd8` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### autogen
- Root: `F:\DevHub\_tmp_competitor_autogen`
- Version: `13e144e5476a76ca0d76bf4f07a6401d133a03ed` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### crewai
- Root: `F:\DevHub\_tmp_competitor_crewai`
- Version: `87759cdb1417576f78460bc9320b60d79df1c30c` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

### langgraph
- Root: `F:\DevHub\_tmp_competitor_langgraph`
- Version: `a3823395cf0516f0c03ac8c20798328c8cee9abe` (up_to_date=yes)
- Model snapshot: ok=False, day=`2026-03-06`, model=`n/a`
- Strict checks: 0 passed / 0 total
- Benchmark runs used: 0
- Errors: none

## Focus Gaps

- `tests.to_code_file_ratio` (test_rigor): winners `crewai`, gap `0.189347`
- `code.non_python_files` (code_surface): winners `openclaw`, gap `343.0`

## Competitor Pressure

- `openclaw`: beat_metrics `1`, focus_beats `58`, composite_delta `-52.908`
- `crewai`: beat_metrics `1`, focus_beats `38`, composite_delta `-72.802`

## Prediction Evo Scope

### Predicted Next Competitor Focus
- `general_surface_growth` (2 signals)
- `test_depth_and_regression_control` (1 signals)

### Recommended Thomas Counter-Moves
- Monitor breadth growth and preemptively add targeted strict checks in the fastest-growing directories. (2 signals)
- Raise test LOC and e2e breadth for touched subsystems before release gate pass. (1 signals)
