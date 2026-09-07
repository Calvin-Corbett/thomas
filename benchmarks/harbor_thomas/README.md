# Harbor agent adapter for Thomas

Lets [Harbor](https://www.harborframework.com) drive Thomas as the agent under
test, so Thomas can be evaluated on terminal benchmarks such as Long-Horizon
Terminal-Bench (LHTB).

```bash
export THOMAS_CODEX_REFRESH_TOKEN=...        # host shell only -- never --ae; see below

PYTHONPATH=benchmarks harbor run \
  -d long-horizon-terminal-bench \
  -a "harbor_thomas.agent:ThomasAgent" \
  -m "gpt-5.6-sol" \
  -k 1 \
  --agent-setup-timeout-multiplier 6 \
  --ak agent_timeout_sec=5400 \
  --ak repo_ref=<commit-sha> \
  --ak reasoning_effort=xhigh
```

`PYTHONPATH` is load-bearing: Harbor does no `sys.path` manipulation when
resolving an agent import path, so the package must already be importable by
the interpreter running `harbor`.

`--agent-setup-timeout-multiplier` is **not optional**. Harbor wraps all of
`setup()` in `asyncio.wait_for` with `_AGENT_SETUP_TIMEOUT_SEC = 360`
(`harbor/trial/trial.py`), and `install()` does apt-get + `git clone` +
`pip install` from source, which does not fit in six minutes. There is no
`--agent-override-setup-timeout-sec` flag, and `--ak override_setup_timeout_sec`
is silently dropped for import-path agents, so the multiplier is the only lever.

> `--agent-import-path` still works but is deprecated in Harbor 0.22.0; the
> import path goes to `-a`/`--agent` directly.

## Configuration

Passed as `--ak key=value`. Unrecognised keys raise `TypeError` rather than
being ignored, so a typo in `repo_ref` cannot silently benchmark a moving
target.

| Key | Default | Purpose |
| --- | --- | --- |
| `repo_url` | `https://github.com/Calvin-Corbett/thomas` | Thomas source. Not on PyPI, so it is cloned. |
| `repo_ref` | `main` | Ref to pin. **Pin a commit SHA for a submission.** |
| `provider` | `openai_codex` | Thomas LLM provider id. See "Model access". |
| `base_url` | per provider | Provider base URL. |
| `reasoning_effort` | unset | `none\|low\|medium\|high\|xhigh\|max`. Only sent on `openai_codex`. |
| `max_tokens` | `16384` | Mirrors Thomas' own profile. See "Model configuration". |
| `context_window` | `200000` | Mirrors Thomas' own profile. See "Model configuration". |
| `autonomy_level` | `4` | Full auto. Below 4 the agent can stall waiting on a human. |
| `agent_timeout_sec` | unset | The harness budget, for the container-side guard. |
| `timeout_grace_sec` | `120` | How far inside that budget to stop. |
| `block_benchmark_hosts` | `true` | Blackhole the benchmark's own hosts. |

## Model access

The GPT-5.6 models (`gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`) are reached
over the `openai_codex` provider, which talks to ChatGPT's Codex Responses
endpoint. That is also the **only** provider path that transmits
`reasoning_effort`: the dispatch in `thomas/core/llm_client.py:701` routes
`openai_codex` and `anthropic` to their own streams and everything else —
including plain `openai` — to `stream_openai`, which never reads the field.
Declaring a reasoning tier while running on any other provider would be a false
claim.

### Credential handling

Export the refresh token in the host shell. **Do not pass it with `--ae`:**

```bash
export THOMAS_CODEX_REFRESH_TOKEN=...
```

This is not a style preference. Harbor applies every `--ae` value to every
`exec` as a scoped overlay at the highest precedence
(`harbor/trial/trial.py:504,535,1453` → `environments/base.py:416-432` →
`docker.py:1156-1158`), so `--ae` hands the value to the container. The host
process environment is never forwarded. Since the agent under test runs as root
with a shell, `sandbox_root=/` and open egress, a refresh token passed via
`--ae` would sit in front of it for the whole trial — and a refresh token mints
access tokens indefinitely and survives access-token rotation.

The adapter reads the token from the host environment and **refuses to start**
if it finds `THOMAS_CODEX_REFRESH_TOKEN` or `THOMAS_CODEX_ACCESS_TOKEN` in
`--ae`, so this cannot be got wrong silently.

> If you have already run a job with the token passed via `--ae`, rotate the
> ChatGPT OAuth grant. Harbor's end-of-trial scrubber skips any file with a NUL
> byte in its first 8 KiB, so a clean scrub is not proof of absence.

`codex_broker.py` holds the refresh token **on the host** and mints a fresh
access token per trial; `codex_bridge.py` is uploaded into the container as
`sitecustomize.py` and resolves only that short-lived access token. Two reasons:

- The refresh grant **rotates**. An exchange can return a new refresh token and
  invalidate the one presented. Refreshing inside a per-trial container would
  strand each rotation in a container that is then destroyed, so the next trial
  would present an invalidated token and every trial after the first refresh
  would fail — the exact multi-hour failure the bridge exists to prevent.
- The longer-lived secret stays off the task environment — provided it is
  exported rather than passed with `--ae`, which the adapter enforces. That
  matters because the agent
  under test is executing arbitrary commands as root.

`api_key` is deliberately left unset for this provider: it takes precedence over
the resolver (`thomas/core/llm_streaming.py:336-338`), so setting it would pin
one token for the whole job.

For other providers the key is read from `THOMAS_API_KEY`,
`ANTHROPIC_API_KEY`, or `OPENAI_API_KEY`.

## Model configuration

`max_tokens` and `context_window` are set explicitly and **must not be dropped**.
Env overrides build the models table themselves, which skips the built-in
profile block in `thomas/core/config.py:793-800`. Anything that block would have
set has to be set here too, or the profile silently falls back to
`ModelConfig`'s bare defaults of `4096` / `8192` — against Thomas' own
`openai_codex` values of `16384` / `200000`, a ~24x context reduction.
`thomas/agent/loop_core.py:190` then trims history to that window without
warning and `config.validate()` returns no error. On a long-horizon benchmark
this understates the system under test rather than failing visibly.

## Design decisions that affect result validity

**Provider errors are re-raised; Thomas' own non-zero exits are not.** `run()`
uses `environment.exec` and then classifies the failure. Thomas exits non-zero
in states normal for a long-horizon run — `1` on agent error, which includes
exhausting its 400-pass runaway guard, and `3` on interrupt — and marking those
errored would misreport tasks the verifier may well have passed. Provider
failures are different: Harbor drives retries off
`exception_info.exception_type` (`harbor/trial/queue.py`), so swallowing an
`ApiRateLimitError` costs a trial that a retry would have recovered. Those are
re-raised. The verifier runs in either case
(`harbor/trial/single_step.py:83-88` catches and records, then verification
proceeds).

**`set -o pipefail` is required.** `run()` pipes Thomas into `tee`, and without
`pipefail` the recorded exit status is *tee's* — always `0`, making every run
look successful regardless of what Thomas did. `BaseInstalledAgent._exec` adds
the prefix for you; `environment.exec` does not, so it is set explicitly.

**`run()` must leave the `AgentContext` empty.** Harbor skips
`populate_context_post_run` when the context is already non-empty
(`Trial._populate_agent_context` returns early on `not agent_result.is_empty()`).
Writing anything to the context during `run()` silently suppresses all token
accounting for that trial. Every context field is therefore set in the hook,
which still runs after a timeout or non-zero exit because the trial syncs agent
output in a `finally` block.

**Thomas runtime flags are not optional.** `run()` sets:

- `THOMAS_ENV=development` — production mode force-disables the shell tool with
  no override, leaving the agent unable to run any command at all.
- `THOMAS_TOOLS_ALLOW_SHELL=true` — the shell tool is off by default.
- `THOMAS_NO_AUTO_UPDATE=1` — the updater otherwise runs
  `pip install --upgrade` mid-trial, mutating the agent under test.
- `THOMAS_TOOLS_SANDBOX_ROOT=/` — filesystem tools are confined to the sandbox
  root, and task files live outside any single project directory.
- `THOMAS_DEFAULT_MODEL` plus an explicit `THOMAS_MODELS_BENCH_*` block —
  Thomas reads no vendor-standard variable, and once env overrides create a
  models table an unset default fails config validation with exit 2.

**Reward-hacking guard.** `install()` blackholes the benchmark's own site and
repository in `/etc/hosts`. This is a backstop for honest runs, **not** a
security control: it covers four names only, IPv6 lookups can bypass it, and the
agent runs as root with `sandbox_root=/` so it could simply re-edit the file.
The harness network policy is the real control. Disable with
`--ak block_benchmark_hosts=false` if a maintainer objects to the environment
being mutated, or if a task legitimately needs one of those hosts.

### Open risk: the access token cannot refresh mid-trial

`run()` injects one access token into the container environment, and an
environment cannot be changed after the process starts. A trial that outlives
the access token's lifetime starts failing authentication partway through, and
the verifier then grades whatever partial state exists. With a 90-minute agent
budget and a token lifetime around an hour, this can affect a meaningful share
of trials.

It is the direct cost of keeping the refresh token out of the container, which
is deliberate: the agent under test runs arbitrary commands as root, and
everything it prints is published with the submission. The options are:

- **Measure first.** Decode the `exp` of a real access token and compare it to
  the agent budget. If the lifetime exceeds 90 minutes there is no problem.
- **Shorten the agent budget** so a trial cannot outlive one token.
- **Accept in-container refresh**, passing the refresh token in and writing
  rotations back to the host. This fixes the lifetime problem and reintroduces
  the exposure; it is not implemented here.

Do not leave this undecided before a long run: the failure is partial and
silent, and shows up as unexplained low scores rather than as errors.

## Known limitations

- **The container-side timeout does not preserve token accounting.** Thomas
  prints its token summary inside the `try` block that `KeyboardInterrupt`
  unwinds (`thomas/cli/_commands_base.py:434-440`, `:645`), so a run stopped by
  the guard reports no tokens. The guard's value is that Thomas exits through
  its own code path and the trial is not cancelled mid-await; only a run that
  finishes on its own reports usage. Budget for a share of trials with no token
  data.
- **The guard is off unless `agent_timeout_sec` is passed**, and it is a
  hand-duplicated value. Nothing reconciles it with Harbor's computed budget,
  which is `min(override_timeout_sec or task timeout, max_timeout_sec) x
  multiplier`. If you pass a non-default `--timeout-multiplier`, recompute
  `agent_timeout_sec` to match or the guard lands outside the real budget.
- **`mcp_servers` and `skills_dir` are accepted and ignored.** A task declaring
  MCP servers or skills runs without them.
- Thomas reports no cost, so `cost_usd` is left unset rather than derived from a
  guessed price table. Compute cost from the token counts and your own rates.
- `sitecustomize.py` on `PYTHONPATH` loads for every Python process the agent
  starts, including any Python the task under test runs. It imports `thomas` at
  each interpreter start.
- `THOMAS_TOOLS_SANDBOX_ROOT=/` means Thomas' runtime-protection guard blocks
  writes to a few top-level paths (`/scripts`, `/thomas`, ...).
- `THOMAS_DATA_DIR` points inside the published trial log directory, so Thomas'
  memory store ships with the submission. No credential lands there on the
  codex path, but review it before publishing.
