# Full Coverage Test Suite

This document is the full test-suite contract for Thomas.

- Contract id: `thomas-full-coverage-contract-v1`
- Contract version: `1`
- Generated at (UTC): `2026-02-21T19:34:15Z`
- Runtime metrics (auto-included from suite metric board): `110`
- Catalog checks (explicit): `210`
- Catalog implemented today: `210`
- Execution policy: quality_is_king=`True`, cycle_limit_disabled=`True`
- Stop condition: `Continue until no known meaningful gaps remain or user explicitly stops.`
- Policy reference: `docs/QUALITY_EXECUTION_POLICY.md`

## Runtime Metric Board (Current)

- `benchmark.avg_elapsed_seconds_mean`
- `benchmark.avg_elapsed_seconds_stddev`
- `benchmark.credibility_weighted_score_mean`
- `benchmark.evidence_coverage_mean`
- `benchmark.failure_rate_mean`
- `benchmark.raw_elapsed_seconds_mean`
- `benchmark.raw_elapsed_seconds_p95`
- `benchmark.raw_elapsed_seconds_stddev`
- `benchmark.raw_rows_count`
- `benchmark.raw_success_rate_mean`
- `benchmark.runs_count`
- `benchmark.success_rate_mean`
- `benchmark.success_rate_stddev`
- `benchmark.weighted_score_mean`
- `benchmark.weighted_score_stddev`
- `browser.files`
- `browser.loc`
- `cli.depth.acp`
- `cli.depth.agents`
- `cli.depth.approvals`
- `cli.depth.browser`
- `cli.depth.channels`
- `cli.depth.clawbot`
- `cli.depth.config`
- `cli.depth.cron`
- `cli.depth.daemon`
- `cli.depth.devices`
- `cli.depth.directory`
- `cli.depth.dns`
- `cli.depth.gateway`
- `cli.depth.help`
- `cli.depth.hooks`
- `cli.depth.memory`
- `cli.depth.message`
- `cli.depth.models`
- `cli.depth.node`
- `cli.depth.nodes`
- `cli.depth.pairing`
- `cli.depth.plugins`
- `cli.depth.sandbox`
- `cli.depth.security`
- `cli.depth.skills`
- `cli.depth.system`
- `cli.depth.update`
- `cli.depth.webhooks`
- `cli.depth_total`
- `cli.top_level_commands`
- `code.non_python_files`
- `code.python_files`
- `config.files`
- `cost.benchmark_tokens_per_success`
- `cost.benchmark_tool_calls_per_success`
- `cost.benchmark_total_tokens_mean`
- `cost.probes.avg_elapsed_seconds`
- `cost.probes.failed_runs`
- `cost.probes.pass_rate`
- `cost.probes.passed_runs`
- `cost.probes.total_runs`
- `docs.markdown_files`
- `extensions.directories`
- `gateway.openai_chat_completions.files`
- `gateway.openai_chat_completions.occurrences`
- `gateway.responses.files`
- `gateway.responses.occurrences`
- `integrity.empty_code_files`
- `integrity.empty_production_asset_files`
- `integrity.invalid_json_files`
- `integrity.missing_required_paths`
- `integrity.python_syntax_errors`
- `loc.total_files`
- `loc.total_loc`
- `maintainability.large_code_files_over_800`
- `mobile_surface.directories`
- `performance.load.avg_elapsed_seconds`
- `performance.load.avg_throughput`
- `performance.load.failed_runs`
- `performance.load.p95_elapsed_seconds`
- `performance.load.pass_rate`
- `performance.load.passed_runs`
- `performance.load.total_runs`
- `plugins.files`
- `plugins.loc`
- `production.strict_checks.assertion_failures`
- `production.strict_checks.avg_elapsed_seconds`
- `production.strict_checks.command_failures`
- `production.strict_checks.failed`
- `production.strict_checks.pass_rate`
- `production.strict_checks.passed`
- `production.strict_checks.total`
- `resilience.probes.avg_elapsed_seconds`
- `resilience.probes.failed_runs`
- `resilience.probes.p95_elapsed_seconds`
- `resilience.probes.pass_rate`
- `resilience.probes.passed_runs`
- `resilience.probes.total_runs`
- `scripts.files`
- `security.probes.avg_elapsed_seconds`
- `security.probes.failed_runs`
- `security.probes.pass_rate`
- `security.probes.passed_runs`
- `security.probes.total_runs`
- `security.risky_construct_files`
- `security.risky_construct_hits`
- `security.secret_like_files`
- `security.secret_like_hits`
- `tests.files`
- `tests.loc`
- `tests.loc_per_file`
- `tests.to_code_file_ratio`
- `tests.to_code_loc_ratio`

## Expanded Full-Coverage Catalog

### agent_runtime

- `core.041` [implemented] Agent routing correctness tests.
- `core.042` [implemented] Tool-selection policy tests.
- `core.043` [implemented] Tool argument schema tests.
- `core.044` [implemented] Tool-call timeout handling tests.
- `core.045` [implemented] Tool-call cancellation tests.
- `core.046` [implemented] Tool-call partial-failure recovery tests.
- `core.047` [implemented] Agent memory write/read consistency tests.
- `core.048` [implemented] Memory contradiction detection tests.
- `core.049` [implemented] Memory curation quality tests.
- `core.050` [implemented] Context-window truncation safety tests.
- `core.051` [implemented] Prompt-injection resistance tests.
- `core.052` [implemented] Data-exfiltration refusal tests.
- `core.053` [implemented] Unsafe-action refusal tests.
- `core.054` [implemented] Policy override resistance tests.
- `core.055` [implemented] Model fallback correctness tests.
- `core.056` [implemented] Multi-provider model parity tests.
- `core.057` [implemented] Deterministic replay tests of agent runs.
- `core.058` [implemented] Long-conversation coherence tests.
- `core.059` [implemented] Task planning/execution parity tests.
- `core.060` [implemented] Hallucination guardrail tests with known answers.

### agentic_native

- `agentic.001` [implemented] Hard-constraint violation rate across full runs.
- `agentic.002` [implemented] Constraint persistence after long context windows (drift test).
- `agentic.003` [implemented] Plan-to-action divergence score (did execution match declared plan).
- `agentic.004` [implemented] Replan quality after mid-run objective change.
- `agentic.005` [implemented] Tool precondition verification recall (caught bad preconditions before calling).
- `agentic.006` [implemented] Tool side-effect blast-radius score (minimal write/change surface).
- `agentic.007` [implemented] Retry idempotency correctness under duplicate/partial failures.
- `agentic.008` [implemented] Compensation/rollback correctness after failed multi-step actions.
- `agentic.009` [implemented] Confidence calibration score (Brier/ECE for success predictions).
- `agentic.010` [implemented] Correct abstention rate when evidence is insufficient.
- `agentic.011` [implemented] Claim-to-evidence traceability completeness (every claim backed by artifact).
- `agentic.012` [implemented] Phantom-work detection (claims action done when no receipt exists).
- `agentic.013` [implemented] Long-horizon commitment retention across many turns.
- `agentic.014` [implemented] Memory poisoning resistance (malicious facts injected earlier).
- `agentic.015` [implemented] Memory pruning precision (forgets stale data, keeps critical commitments).
- `agentic.016` [implemented] Instruction hierarchy fidelity (system/dev/user conflict handling).
- `agentic.017` [implemented] Delayed jailbreak robustness (payload hidden over multiple turns).
- `agentic.018` [implemented] Social-engineering approval bypass resistance.
- `agentic.019` [implemented] Interruptibility latency (how fast the agent safely stops/redirects).
- `agentic.020` [implemented] Human override compliance correctness.
- `agentic.021` [implemented] Handoff quality score (state transfer with no loss).
- `agentic.022` [implemented] Delegation quality in multi-agent mode (right task to right specialist).
- `agentic.023` [implemented] Coordination overhead efficiency (extra chatter vs value gained).
- `agentic.024` [implemented] Unseen tool schema adaptation success.
- `agentic.025` [implemented] Temporal-awareness correctness (date/time-dependent decisions).
- `agentic.026` [implemented] Distribution-shift robustness (new domain/task family not in corpus).
- `agentic.027` [implemented] Benchmark anti-gaming checks (no metric-optimized but useless behavior).
- `agentic.028` [implemented] Counterfactual tool-choice quality (was chosen tool actually best).
- `agentic.029` [implemented] Self-critique utility score (reflection improves outcome).
- `agentic.030` [implemented] Operator trust score (predictable, controllable, auditable under stress).

### browser_and_operator_ux

- `core.061` [implemented] Browser workflow corpus validity tests.
- `core.062` [implemented] Browser workflow runtime execution tests.
- `core.063` [implemented] Browser profile coverage tests.
- `core.064` [implemented] Browser extension interaction tests.
- `core.065` [implemented] DOM-selector drift resilience tests.
- `core.066` [implemented] Browser timeout/retry tests.
- `core.067` [implemented] Desktop viewport visual regression tests.
- `core.068` [implemented] Mobile viewport visual regression tests.
- `core.069` [implemented] Accessibility keyboard-nav tests.
- `core.070` [implemented] Accessibility ARIA/semantic tests.
- `core.071` [implemented] Accessibility contrast tests.
- `core.072` [implemented] Frontend error boundary tests.
- `core.073` [implemented] Frontend state restoration tests.
- `core.074` [implemented] Frontend offline behavior tests.
- `core.075` [implemented] Frontend slow-network behavior tests.
- `core.076` [implemented] Service worker/cache correctness tests.
- `core.077` [implemented] Client-side auth/session expiry tests.
- `core.078` [implemented] Cross-browser matrix tests (Chrome/Edge/Firefox).
- `core.079` [implemented] Mobile emulation matrix tests.
- `core.080` [implemented] UI telemetry event contract tests.

### compliance_and_competitive_intel

- `core.161` [implemented] Compliance logging completeness tests.
- `core.162` [implemented] GDPR delete/export flow tests.
- `core.163` [implemented] SOC2 control evidence tests.
- `core.164` [implemented] Data residency routing tests.
- `core.165` [implemented] Accessibility compliance gates (WCAG).
- `core.166` [implemented] Terms/policy enforcement tests.
- `core.167` [implemented] Content moderation pipeline tests.
- `core.168` [implemented] Abuse-rate limiting tests.
- `core.169` [implemented] Multi-tenant isolation tests.
- `core.170` [implemented] Tenant billing boundary tests.
- `core.171` [implemented] Competitor catalog freshness tests.
- `core.172` [implemented] Competitor auto-clone/update tests.
- `core.173` [implemented] Competitor version capture tests.
- `core.174` [implemented] Daily model snapshot enforcement tests.
- `core.175` [implemented] Competitor pressure-board correctness tests.
- `core.176` [implemented] Prediction-evo-scope delta detection tests.
- `core.177` [implemented] Prediction-evo-scope recommendation validity tests.
- `core.178` [implemented] Benchmark corpus anti-gaming checks.
- `core.179` [implemented] Cross-run comparability normalization checks.
- `core.180` [implemented] Historical trend regression alerts.

### coverage_and_correctness

- `core.001` [implemented] Global line coverage gate.
- `core.002` [implemented] Global branch coverage gate.
- `core.003` [implemented] Global function coverage gate.
- `core.004` [implemented] Per-package line coverage minimums.
- `core.005` [implemented] Per-package branch coverage minimums.
- `core.006` [implemented] Diff coverage gate on changed files.
- `core.007` [implemented] Mutation testing minimum score.
- `core.008` [implemented] Unit tests for every public function.
- `core.009` [implemented] Unit tests for every error branch.
- `core.010` [implemented] Unit tests for serialization/deserialization.
- `core.011` [implemented] Property-based tests for core parsers.
- `core.012` [implemented] Property-based tests for validators.
- `core.013` [implemented] Metamorphic tests for deterministic transforms.
- `core.014` [implemented] Golden tests for stable outputs.
- `core.015` [implemented] Snapshot tests for structured payloads.
- `core.016` [implemented] Fuzz tests for input parsers.
- `core.017` [implemented] Unicode/encoding edge-case tests.
- `core.018` [implemented] Timezone and DST correctness tests.
- `core.019` [implemented] Locale/i18n formatting correctness tests.
- `core.020` [implemented] Cross-platform path handling tests.

### extensions_and_state

- `core.081` [implemented] Extension catalog schema tests.
- `core.082` [implemented] Extension catalog runtime load tests.
- `core.083` [implemented] Extension install tests.
- `core.084` [implemented] Extension upgrade tests.
- `core.085` [implemented] Extension rollback tests.
- `core.086` [implemented] Extension uninstall cleanup tests.
- `core.087` [implemented] Extension dependency conflict tests.
- `core.088` [implemented] Extension sandbox/permission tests.
- `core.089` [implemented] Extension API compatibility version tests.
- `core.090` [implemented] Extension cold-start performance tests.
- `core.091` [implemented] DB migration forward tests.
- `core.092` [implemented] DB migration rollback tests.
- `core.093` [implemented] Corrupt-data recovery tests.
- `core.094` [implemented] Backup/restore integrity tests.
- `core.095` [implemented] Concurrency lock/race-condition tests.
- `core.096` [implemented] Transaction atomicity tests.
- `core.097` [implemented] Data retention/purge tests.
- `core.098` [implemented] PII redaction correctness tests.
- `core.099` [implemented] Audit log integrity tests.
- `core.100` [implemented] Cross-version state compatibility tests.

### interfaces_and_protocols

- `core.021` [implemented] CLI command existence contract tests.
- `core.022` [implemented] CLI help/usage schema tests.
- `core.023` [implemented] CLI argument normalization tests.
- `core.024` [implemented] CLI invalid-arg failure-mode tests.
- `core.025` [implemented] CLI exit-code contract tests.
- `core.026` [implemented] API schema conformance tests (request).
- `core.027` [implemented] API schema conformance tests (response).
- `core.028` [implemented] OpenAI-compat gateway protocol tests.
- `core.029` [implemented] Streaming response event-order tests.
- `core.030` [implemented] Retry/idempotency behavior tests.
- `core.031` [implemented] Pagination correctness tests.
- `core.032` [implemented] Rate-limit behavior tests.
- `core.033` [implemented] AuthN failure tests.
- `core.034` [implemented] AuthZ failure tests.
- `core.035` [implemented] Backward-compat API version tests.
- `core.036` [implemented] Webhook signature verification tests.
- `core.037` [implemented] Webhook replay-protection tests.
- `core.038` [implemented] WebSocket connect/disconnect tests.
- `core.039` [implemented] WebSocket backpressure tests.
- `core.040` [implemented] WebSocket reconnect recovery tests.

### performance_and_cost

- `core.121` [implemented] Cold-start latency benchmarks.
- `core.122` [implemented] Warm-path latency benchmarks.
- `core.123` [implemented] P50/P95/P99 latency gates.
- `core.124` [implemented] Throughput saturation tests.
- `core.125` [implemented] Concurrency scaling tests.
- `core.126` [implemented] Memory leak soak tests.
- `core.127` [implemented] CPU regression gates.
- `core.128` [implemented] I/O regression gates.
- `core.129` [implemented] Queue depth/backlog stress tests.
- `core.130` [implemented] Autoscaling behavior tests.
- `core.131` [implemented] Tail-latency under failure tests.
- `core.132` [implemented] Load-shedding behavior tests.
- `core.133` [implemented] Graceful degradation tests.
- `core.134` [implemented] Thundering-herd prevention tests.
- `core.135` [implemented] Cache hit-rate regression tests.
- `core.136` [implemented] Cache invalidation correctness tests.
- `core.137` [implemented] Cost-per-task regression gates.
- `core.138` [implemented] Token-per-success regression gates.
- `core.139` [implemented] Tool-call-per-success regression gates.
- `core.140` [implemented] Provider spend-cap enforcement tests.

### reliability_and_release_ops

- `core.141` [implemented] Flakiness detection and quarantine pipeline.
- `core.142` [implemented] Test repeatability checks (N reruns).
- `core.143` [implemented] Randomized test-order stability checks.
- `core.144` [implemented] Hermetic test environment checks.
- `core.145` [implemented] Seeded reproducibility checks.
- `core.146` [implemented] Fixture isolation checks.
- `core.147` [implemented] Clock-freeze deterministic tests.
- `core.148` [implemented] CI timeout budget tests.
- `core.149` [implemented] Parallel test safety checks.
- `core.150` [implemented] Artifact retention and traceability checks.
- `core.151` [implemented] Release-candidate smoke suite.
- `core.152` [implemented] Release rollback drills.
- `core.153` [implemented] Blue/green deployment tests.
- `core.154` [implemented] Canary gating tests.
- `core.155` [implemented] Post-deploy synthetic transaction tests.
- `core.156` [implemented] SLO/error-budget gate checks.
- `core.157` [implemented] Alert routing correctness tests.
- `core.158` [implemented] On-call runbook execution drills.
- `core.159` [implemented] Disaster-recovery failover tests.
- `core.160` [implemented] Regional outage simulation tests.

### security_depth

- `core.101` [implemented] SAST gate (high/critical fail).
- `core.102` [implemented] DAST gate for exposed endpoints.
- `core.103` [implemented] Secret scanning gate.
- `core.104` [implemented] Dependency vulnerability gate (runtime).
- `core.105` [implemented] Dependency vulnerability gate (dev-time).
- `core.106` [implemented] License policy gate.
- `core.107` [implemented] SBOM generation + diff gate.
- `core.108` [implemented] Artifact provenance/signature verification.
- `core.109` [implemented] Sandbox escape attempt tests.
- `core.110` [implemented] Command injection tests.
- `core.111` [implemented] SQL injection tests.
- `core.112` [implemented] XSS tests.
- `core.113` [implemented] CSRF tests.
- `core.114` [implemented] SSRF tests.
- `core.115` [implemented] Path traversal tests.
- `core.116` [implemented] Zip-slip/file extraction tests.
- `core.117` [implemented] Unsafe deserialization tests.
- `core.118` [implemented] Cryptography misuse tests.
- `core.119` [implemented] Session fixation/hijack tests.
- `core.120` [implemented] Security regression replay suite.
