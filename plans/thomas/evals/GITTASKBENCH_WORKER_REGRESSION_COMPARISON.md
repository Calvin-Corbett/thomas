# GitTaskBench Worker Regression Comparison

> Date: 2026-06-28
> Scope: Planning artifact for ranked item 15, "GitTaskBench Repository-Aware Code-Agent Benchmark".
> Source ranking: `plans/thomas/AGENTIC_AI_FEATURE_RANKINGS.md`, rank 15.
> External source inspected: `https://github.com/QuantaAlpha/GitTaskBench` README and sample `queries/Trafilatura_01/query.json` / `config/Trafilatura_01/task_info.yaml`.

## Purpose

GitTaskBench is useful to Thomas because it treats a task as more than a patch:
the worker must understand a repository, satisfy setup and dependency
requirements, produce task outputs, and pass task-specific checks. That matches
Thomas's weakest regression surface better than pure issue-to-diff benchmarks:
many Thomas worker failures are environment, evidence, coordination, or artifact
failures rather than code-generation failures.

This document compares the GitTaskBench task format with the minimum Thomas
worker regression-suite needs. It is not an implementation. The next safe slice
is a small local fixture modeled after GitTaskBench without importing the full
benchmark or its heavyweight dependencies.

## GitTaskBench Task Dimensions

GitTaskBench organizes each task around a fixed repository plus separate task,
configuration, output, ground-truth, and evaluator paths:

| Dimension | GitTaskBench shape | Regression value for Thomas |
|---|---|---|
| Task identity | `task_id`, for example `Trafilatura_01` | Stable fixture id for reruns, dashboards, and regression history. |
| Natural-language objective | `task_description` in `queries/<task>/query.json` | Preserves the user's work request as the worker-facing goal. |
| Repository context | `repositories[]` with `name`, `path`, `url`, and optional understanding guidelines | Forces the runner to prove it used the intended repo instead of a generic answer. |
| Working directory | `working_sub_directory_name` | Gives each task an isolated output workspace under a deterministic path. |
| Input files | `file_paths.input_files[]` with path and description | Separates prompt text from artifacts the worker must read. |
| Agent prompt | `prompt_file` | Allows runner-specific prompt generation without mutating the task definition. |
| Evaluation config | `config/<task>/task_info.yaml` with `result`, `output_dir`, `groundtruth`, `test_script`, and `multi_output` | Gives the regression runner a machine-readable scoring contract. |
| Expected output | `output_dir` and task-specific output filenames | Captures artifact production, not only console success. |
| Ground truth | `groundtruth/<task>/...` | Supports deterministic comparison or domain-specific scoring. |
| Test script | `test_scripts/<task>/test_script.py` | Keeps scoring logic task-specific while preserving a common runner interface. |
| Score report | `results.jsonl` plus aggregate eval report | Gives post-run evidence for process success and task pass rate. |

## Thomas Worker Regression Needs

Thomas needs a smaller fixture format that can run locally in CI and in dirty
developer checkouts. The fixture should evaluate worker behavior that current
unit tests cannot fully cover:

| Need | Required field or behavior | Why it matters |
|---|---|---|
| Repo-aware execution | `repo_root`, `allowed_paths`, and expected touched files | Catches workers that ignore the checkout, edit outside scope, or hallucinate files. |
| Claim discipline | `claim_scope` and optional forbidden paths | Ensures future worker tests preserve unrelated dirty files and avoid protected surfaces. |
| Environment setup | `setup.commands`, `setup.required_files`, `setup.network_policy`, `setup.timeout_seconds` | Makes setup failure an explicit outcome instead of an opaque test crash. |
| Dependency handling | `dependencies.allowed_install_commands` and cache policy | Distinguishes missing dependency detection from unsafe installation behavior. |
| Task execution | `worker_prompt`, input artifacts, and expected output paths | Tests full worker loop from instruction to artifact. |
| Evidence capture | `evidence.required_commands`, `evidence.required_logs`, `evidence.changed_files` | Forces final reports to cite concrete proof. |
| Scoring | `scoring.process_checks`, `scoring.result_checks`, and `scoring.pass_threshold` | Mirrors GitTaskBench's completion/pass split while fitting Thomas evidence packs. |
| Cost and time | `limits.max_minutes`, `limits.max_tokens`, optional model budget | Prevents benchmark regressions from normalizing runaway worker loops. |
| Reproducibility | fixture version, source commit, and deterministic seed where relevant | Lets a failed worker run be replayed and compared across changes. |
| Safety | `forbidden_commands`, secret policy, and output scrub rules | Keeps repo-worker evals from becoming a path around Thomas guardrails. |

## Mapping

| GitTaskBench concept | Thomas local fixture equivalent | Adaptation decision |
|---|---|---|
| `queries/<task>/query.json` | `tests/fixtures/worker_regression/<task>/task.yaml` or JSON | Keep one machine-readable fixture file; include prompt, repo, input, claim, and evidence contract. |
| Fixed `code_base/<repo>` checkout | Existing Thomas test fixture repo, synthetic mini repo, or temporary copied repo | Do not vendor external benchmark repos into Thomas for the first slice. Use a tiny local repo fixture. |
| `prompt_file` per framework | Generated worker prompt from fixture fields | Thomas should own prompt construction so task files stay framework-neutral. |
| `config/<task>/task_info.yaml` | `evaluation` block in the fixture | Collapse config into the fixture until there are enough tasks to justify separate config files. |
| `groundtruth/<task>` | `expected/` directory beside the fixture | Keep expected outputs close to fixture inputs for small local cases. |
| `test_scripts/<task>/test_script.py` | A shared pytest runner plus optional task-specific checker module | Start with shared checks; allow checker extension only when a task needs domain scoring. |
| `output/<task>` | `tmp_path / worker_regression / <task>` | Never write benchmark outputs into the repo by default. |
| `results.jsonl` | JSONL evidence record plus pytest assertion summary | Preserve run-level evidence for dashboards and debugging. |
| Execution completion rate | `process_pass` boolean | Passes only if setup, worker run, and artifact collection complete. |
| Task pass rate | `result_pass` boolean plus score details | Passes only if output semantics match the fixture contract. |

## Gaps To Close Before Implementation

1. **No canonical Thomas worker-regression fixture schema yet.** A future slice
   should add one fixture parser and one sample fixture before adding broad
   benchmark support.
2. **Setup/dependency policy needs a narrow first version.** GitTaskBench assumes
   benchmark-specific environments; Thomas needs a safe local rule for when a
   worker may install dependencies, use network, or skip setup.
3. **Output evidence should be first-class.** Thomas should score not only final
   files but also whether the worker reported the right commands, changed files,
   and residual risks.
4. **Dirty-checkout preservation must be part of the fixture.** GitTaskBench
   isolates benchmark repos; Thomas often runs in a shared checkout. Regression
   tests should create known dirty sentinel files and prove they remain
   unchanged.
5. **Scoring must separate "could not set up" from "wrong result".** GitTaskBench
   distinguishes execution completion from task pass rate. Thomas should retain
   that split to avoid hiding environment failures under generic test failures.
6. **Fixture scale should stay small.** The first Thomas implementation should
   not pull in 54 multimodal GitTaskBench tasks, conda, GPU dependencies, or
   heavyweight external repositories.

## Minimum Local Fixture Shape

The smallest useful Thomas fixture can be a generated temporary repo with one
bug, one task prompt, and one expected file or test result:

```yaml
schema_version: 1
task_id: local_repo_worker_001
title: Fix a repo-local CLI output bug
worker_prompt: >
  In the provided repository, fix the CLI so `python -m demo greet Ada`
  prints `Hello, Ada!`. Preserve unrelated dirty files.
repo:
  fixture_source: tests/fixtures/worker_regression/local_repo_worker_001/repo
  checkout_mode: copy_to_tmp
  allowed_paths:
    - demo/cli.py
    - tests/test_cli.py
  forbidden_paths:
    - README.md
dirty_sentinels:
  - path: README.md
    content: "operator notes - do not touch"
setup:
  commands:
    - python -m pytest tests/test_cli.py -q
  required_files:
    - pyproject.toml
  network_policy: disabled
  timeout_seconds: 60
execution:
  expected_changed_files:
    - demo/cli.py
  expected_outputs:
    - command: python -m demo greet Ada
      stdout_contains: "Hello, Ada!"
scoring:
  process_checks:
    - setup_completed
    - worker_completed
    - dirty_sentinels_unchanged
  result_checks:
    - focused_tests_passed
    - expected_stdout_matched
  pass_threshold: all
evidence:
  required_fields:
    - commands_run
    - changed_files
    - verification_results
    - residual_risks
```

## Scoring And Evidence Fields

A future Thomas evidence record should be JSONL-friendly and stable enough for
dashboard aggregation:

| Field | Type | Meaning |
|---|---|---|
| `task_id` | string | Fixture id. |
| `fixture_version` | integer | Schema-compatible fixture revision. |
| `worker_id` | string | Worker or harness identity. |
| `repo_fixture_digest` | string | Digest of copied fixture source. |
| `started_at_utc` / `finished_at_utc` | string | Runtime bounds. |
| `setup_status` | enum | `passed`, `failed`, `skipped`, or `blocked`. |
| `process_pass` | boolean | Setup, execution, and evidence collection completed. |
| `result_pass` | boolean | Task-specific output met expectations. |
| `score` | number | Optional normalized score for non-binary tasks. |
| `commands_run` | list | Commands the worker or harness ran. |
| `changed_files` | list | Relative paths changed by the worker. |
| `dirty_sentinel_status` | enum | `unchanged`, `changed`, or `missing`. |
| `output_artifacts` | list | Files produced for scoring. |
| `verification_results` | list | Focused checks and exit codes. |
| `failure_category` | enum | `setup`, `dependency`, `scope`, `execution`, `result`, `evidence`, `timeout`, or `policy`. |
| `residual_risks` | list | Known gaps from the final worker report. |

## Setup And Dependency Handling

The first Thomas implementation should use a conservative setup contract:

- Default network policy is `disabled`.
- Default install policy is "no install commands"; a fixture must explicitly
  allow package installation.
- Fixture setup runs before worker execution and records setup failures as
  `setup_status=failed`.
- Worker verification runs after edits and records both the command and the
  exact result.
- External repositories are not cloned during the first slice. Use a local
  temporary copy of a tiny fixture repository.
- Long-running, multimodal, GPU, browser, or service-dependent tasks should be
  modeled later as optional benchmark lanes, not baseline regression tests.

## Recommended First Implementation Slice

1. Add one local fixture under `tests/fixtures/worker_regression/`.
2. Add a parser for the fixture schema.
3. Add a pytest that copies the fixture repo to `tmp_path`, applies a simulated
   worker patch or invokes a minimal harness, and emits one evidence record.
4. Assert the split between `process_pass` and `result_pass`.
5. Assert dirty sentinel preservation.
6. Keep the fixture offline and under 60 seconds.

## Acceptance Checklist For Future Implementation

- [ ] One local repo-worker fixture exists and runs without network access.
- [ ] Fixture schema includes task identity, prompt, repo source, allowed paths,
      forbidden paths, setup, execution expectations, scoring, and evidence.
- [ ] The runner writes outputs only under a temporary or benchmark output root.
- [ ] The runner distinguishes setup failure, scope violation, execution failure,
      result mismatch, missing evidence, and timeout.
- [ ] At least one test proves unrelated dirty sentinel files are preserved.
- [ ] At least one test proves `process_pass=true` can still have
      `result_pass=false`.
- [ ] Evidence JSONL includes commands, changed files, verification results,
      output artifacts, and residual risks.
- [ ] The implementation does not vendor GitTaskBench's full task corpus,
      external repositories, conda setup, or GPU dependencies.
- [ ] Documentation names GitTaskBench as the inspiration and records why Thomas
      uses a smaller local fixture first.
- [ ] Focused pytest and ruff checks pass for the new parser/runner files.
