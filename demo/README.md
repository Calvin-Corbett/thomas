# Head-to-Head Demo Harness

Run a standardized comparison between assistants (default: `thomas` vs `reference_cli`) and emit reproducible scoring artifacts.

## One-command run

```powershell
python scripts/run_head_to_head_demo.py
```

Default behavior:
- Loads `demo/task_pack.default.json`
- Prompts for observed metrics per task/per competitor
- Enforces complete results (every task x competitor must be scored exactly once)
- Can randomize execution order (`--randomize-order --seed <n>`) for bias control
- Writes artifacts to `demo/runs/<run_id>/`

## Outputs

- `scorecard.json`: weighted ranking + per-competitor metrics
- `results.raw.json`: raw manual observations
- `task_prompts.md`: exact prompts used in the run
- `execution_plan.json` / `execution_plan.md`: exact step order used
- `manifest.json`: run integrity metadata + SHA256 hashes
- `report.md`: publication-ready ranking + per-task winners
- `overlay.csv`: lightweight CSV for video overlays/editing

## Optional flags

```powershell
python scripts/run_head_to_head_demo.py `
  --competitor thomas `
  --competitor reference_cli `
  --task-pack demo/task_pack.default.json `
  --run-id release-demo-001 `
  --template-out demo/results-template.json `
  --randomize-order `
  --seed 42 `
  --require-evidence
```

Scorecard weights are controlled in the task pack (`success_rate`, `speed`, `follow_up`, `quality`).

Generate only a blank results matrix (no scoring run yet):

```powershell
python scripts/run_head_to_head_demo.py `
  --template-out demo/results-template.json `
  --template-only
```

Aggregate multiple runs into one consistency scoreboard:

```powershell
python scripts/run_head_to_head_demo.py `
  --aggregate-from demo/runs
```

Generate blind judging files from an existing run:

```powershell
python scripts/run_head_to_head_demo.py `
  --blind-pack-from demo/runs/release-demo-001 `
  --blind-seed 42
```

Automated dual-browser execution with timestamp capture:

```powershell
python scripts/run_dual_browser_demo.py `
  --target thomas=http://127.0.0.1:8899/ `
  --target reference_cli=http://127.0.0.1:3000/ `
  --selectors-json demo/selectors.example.json `
  --randomize-order `
  --seed 42
```

Dual-browser run outputs include:
- `browser_results.raw.json` (step-by-step timestamps + response text)
- `results.template.from_browser.json` (prefilled harness scoring template)
- `browser_transcripts/*.txt` (prompt/response transcripts per step)

One-command 10-run campaign (execute + score + aggregate + publish pack):

```powershell
python scripts/run_demo_campaign.py `
  --runs-count 10 `
  --target thomas=http://127.0.0.1:8899/ `
  --target reference_cli=http://127.0.0.1:3000/ `
  --selectors-json demo/selectors.example.json `
  --base-seed 42
```

Campaign outputs:
- `demo/campaigns/<campaign_id>/campaign_manifest.json`
- `demo/campaigns/<campaign_id>/aggregate.scorecard.json`
- `demo/campaigns/<campaign_id>/run_index.csv`
- `demo/campaigns/<campaign_id>/REPORT.md`
- `demo/campaigns/<campaign_id>/publish/*` (share-ready copy)

## Agentic Benchmark (Raw vs Thomas OS, local-first)

Run a direct before/after benchmark where:
- baseline = raw model (no Thomas orchestration/tools)
- after = Thomas OS orchestration on the same profile

```powershell
python scripts/run_agentic_benchmark.py `
  --profile local `
  --task-pack demo/task_pack.agentic.local.json
```

Max-budget Thomas mode (embedded runner: thinking + max economy):

```powershell
python scripts/run_agentic_benchmark.py `
  --profile local `
  --thomas-max-mode
```

Max-budget Thomas swarm mode (API runner; requires running Thomas server):

```powershell
python scripts/run_agentic_benchmark.py `
  --profile local `
  --thomas-runner api `
  --thomas-api-base http://127.0.0.1:8899 `
  --thomas-max-mode
```

Agentic benchmark outputs include:
- `before_after.delta.json` (lift metrics)
- `scorecard.json` (weighted ranking)
- `benchmark_results.raw.json` (per-task run + checks)
- `report.md` (summary report)
- `transcripts/*` (prompt/response/check traces)
