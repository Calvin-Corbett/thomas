# Competitor Gap Research - 2026-02-25

Scope: focused competitor research for Thomas against OpenClaw and CrewAI using the repo's canonical comparison suite.

Note: suite defaults currently resolve to `F:\DevHub\Thomas` artifact paths for comparison outputs.

## Runs Executed

1. `python scripts/run_agent_comparison_suite.py --suite-config demo/baselines/agent_comparison_suite.current.json --focus-agent thomas --h2h-a thomas --h2h-b openclaw --top-gaps 25 --write --write-md`
- Computed at: `2026-02-25T16:01:13Z`
- Head-to-head: `thomas=93.671`, `openclaw=6.329`
- Open gaps for Thomas:
  - `benchmark.raw_elapsed_seconds_p95` (winner: `openclaw`, lower better, gap `0.06215`)
  - `benchmark.weighted_score_stddev` (winner: `openclaw`, lower better, gap `5.965341`)
  - `benchmark.raw_elapsed_seconds_stddev` (winner: `openclaw`, lower better, gap `1.670548`)
  - `benchmark.success_rate_stddev` (winner: `openclaw`, lower better, gap `0.089898`)
  - `tests.to_code_file_ratio` (winner: `crewai`, higher better, gap `0.035555`)

2. `python scripts/run_agent_comparison_suite.py --suite-config demo/baselines/agent_comparison_suite.current.json --focus-agent thomas --h2h-a thomas --h2h-b crewai --top-gaps 25 --write --write-md`
- Computed at: `2026-02-25T16:04:32Z`
- Head-to-head: `thomas=98.958`, `crewai=1.042`
- Gaps remained consistent with run #1 (suite-level open gaps are global for focus agent).

## Key Findings

- No competitor beats Thomas on broad capability, but measurable benchmark stability/latency gaps remain versus OpenClaw.
- Test depth density gap remains versus CrewAI on `tests.to_code_file_ratio`.
- Token efficiency remains `n/a` due missing token telemetry coverage, limiting economic competitiveness claims.

## Workboard Action Upload

Tasks uploaded to `plans/thomas/WORKBOARD.md` (`## Up For Grabs`) to close identified gaps:

- `gap-openclaw-benchmark-stability`
- `gap-openclaw-latency-p95`
- `gap-crewai-test-density`
- `gap-token-efficiency-telemetry`
- `gap-large-files-over-800`
- `gap-openclaw-crewai-weekly-refresh`
