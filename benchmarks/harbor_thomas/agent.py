"""Harbor agent adapter that drives Thomas as the agent under test.

Usage::

    PYTHONPATH=benchmarks harbor run -d long-horizon-terminal-bench \
        -a "harbor_thomas.agent:ThomasAgent" -m "<model-id>" -k 1

Design notes that matter for benchmark validity are documented inline; see
``benchmarks/harbor_thomas/README.md`` for the full rationale.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path, PurePosixPath
from typing import Any, override

from harbor.agents.installed.base import (
    AgentAuthenticationError,
    ApiConnectionClosedError,
    ApiError,
    BaseInstalledAgent,
)
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# Thomas' terminal output carries ANSI colour codes; strip them before parsing.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Emitted once at the end of a run by thomas/cli/_commands_base.py:437-440.
_TOKENS_RE = re.compile(
    r"\[tokens:\s*(\d+)\s*prompt\s*\+\s*(\d+)\s*completion\s*=\s*(\d+)\s*total\]"
)

# Hosts the agent under test must never reach: reading the benchmark's own
# site or repository during a trial is reward hacking. Blackholed in /etc/hosts
# during install() so the block is enforced in the container, not merely asked
# for in the prompt.
_BLOCKED_HOSTS = (
    "zli12321.github.io",
    "huggingface.co",
    "www.harborframework.com",
    "harborframework.com",
)

_DEFAULT_BASE_URLS = {
    "anthropic": "https://api.anthropic.com/v1",
    "openai": "https://api.openai.com/v1",
    # thomas/core/codex_provider.py:16
    "openai_codex": "https://chatgpt.com/backend-api/codex",
}

# Provider whose bearer token is resolved by the sitecustomize bridge rather
# than pinned into ModelConfig.api_key. See codex_bridge.py for why.
_CODEX_PROVIDER = "openai_codex"
_BRIDGE_DIR = "/installed-agent/bridge"
_DATA_DIR = "/installed-agent/thomas-data"

# Kwargs Harbor itself may pass into an import-path agent's __init__
# (harbor/trial/trial.py:944-974). Anything else arriving as **kwargs came from
# a --ak flag and is a typo rather than a setting.
_HARBOR_RESERVED_KWARGS = frozenset(
    {
        "logs_dir",
        "model_name",
        "logger",
        "mcp_servers",
        "skills_dir",
        "extra_env",
        "load_trajectory",
        "environment_logs_dir",
        "prompt_template_path",
        "version",
        "config",
    }
)

_OUTPUT_FILENAME = "thomas.txt"
_RUN_LOG_FILENAME = "thomas-run-log.jsonl"


class ThomasAgent(BaseInstalledAgent):
    """Drives the Thomas CLI (``thomas chat``) inside a Harbor task container."""

    # Thomas is a Linux-only CLI; setup() uses apt/pip and POSIX paths.
    SUPPORTS_WINDOWS: bool = False

    def __init__(
        self,
        *args: Any,
        repo_url: str = "https://github.com/Calvin-Corbett/thomas",
        repo_ref: str = "main",
        provider: str = _CODEX_PROVIDER,
        base_url: str | None = None,
        reasoning_effort: str | None = None,
        max_tokens: int = 16384,
        context_window: int = 200000,
        autonomy_level: int = 4,
        agent_timeout_sec: float | None = None,
        timeout_grace_sec: float = 120.0,
        block_benchmark_hosts: bool = True,
        **kwargs: Any,
    ) -> None:
        """Construct the agent.

        Args:
            repo_url: Thomas source repository. Not on PyPI, so it is cloned.
            repo_ref: Commit/tag/branch to pin. Pin a commit for a submission.
            provider: Thomas LLM provider id. ``openai_codex`` reaches the
                GPT-5.6 models over ChatGPT OAuth, and is the only path that
                actually transmits ``reasoning_effort``.
            base_url: Provider base URL; defaults per provider.
            reasoning_effort: Passed through to Thomas' model config. Record the
                exact value used in the submission's metadata.yaml.
            autonomy_level: Thomas autonomy tier. 4 = full auto, required so the
                agent never waits for a human.
            agent_timeout_sec: The harness agent budget, if you want a
                container-side guard slightly inside it. See run().
            timeout_grace_sec: How far inside ``agent_timeout_sec`` to stop.
            block_benchmark_hosts: Blackhole the benchmark's own hosts.

        Raises:
            TypeError: on an unrecognised ``--ak`` key. Harbor forwards those
                verbatim, so a typo in ``--ak repo_ref=<sha>`` would otherwise
                be ignored and silently benchmark an unpinned moving target.
        """
        if provider == _CODEX_PROVIDER and not reasoning_effort:
            # A submission must declare the exact tier it ran at. Left unset the
            # request omits the reasoning field entirely and the model runs at
            # the provider default, so a declared tier would be a false claim.
            raise TypeError(
                "reasoning_effort is required on the openai_codex provider; "
                "pass --ak reasoning_effort=<none|low|medium|high|xhigh|max>."
            )

        unknown = set(kwargs) - _HARBOR_RESERVED_KWARGS
        if unknown:
            raise TypeError(
                f"{type(self).__name__}: unknown --ak key(s): "
                f"{', '.join(sorted(unknown))}"
            )
        super().__init__(*args, **kwargs)
        self._repo_url = repo_url
        self._repo_ref = repo_ref
        self._provider = provider
        self._base_url = base_url
        self._reasoning_effort = reasoning_effort
        # Defaults mirror Thomas' own openai_codex profile
        # (thomas/core/config.py:793-800), not ModelConfig's bare defaults.
        self._max_tokens = int(max_tokens)
        self._context_window = int(context_window)
        self._autonomy_level = int(autonomy_level)
        self._agent_timeout_sec = (
            float(agent_timeout_sec) if agent_timeout_sec is not None else None
        )
        self._timeout_grace_sec = float(timeout_grace_sec)
        self._block_benchmark_hosts = bool(block_benchmark_hosts)
        # Recorded by run(), consumed by populate_context_post_run(). run()
        # must leave the AgentContext empty -- see that hook for why.
        self._exit_code: int | None = None
        # Every secret injected into the container this trial, kept so the
        # published artifacts can be scrubbed. See _redact_published_artifacts.
        self._injected_secrets: set[str] = set()

    @staticmethod
    @override
    def name() -> str:
        return "thomas"

    @override
    def get_version_command(self) -> str | None:
        # `thomas version` is a subcommand; there is no --version flag.
        return "thomas version"

    @override
    def parse_version(self, stdout: str) -> str:
        """Pull the bare version out of `thomas version` output.

        The command prints a banner over several lines, e.g.
        ``  Thomas v0.19.25`` followed by an install-kind note.
        """
        match = re.search(r"v?(\d+\.\d+\.\d+\S*)", _ANSI_RE.sub("", stdout))
        return match.group(1) if match else stdout.strip()

    # ---------------------------------------------------------------- install

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        """Clone Thomas at a pinned ref and install it into the container."""
        await self.ensure_system_dependencies(
            environment,
            (
                "git",
                "curl",
                "ca_certificates",
                "python3",
                "python_pip",
                "python_venv",
                # run() uses `timeout` and `stdbuf`. On images without them
                # (Alpine) the whole invocation dies with 127 and leaves no
                # transcript, which reads as a silent zero.
                "coreutils",
            ),
        )

        if self._block_benchmark_hosts:
            # Deny the agent the benchmark's own site/repo for the whole trial.
            entries = "\\n".join(f"127.0.0.1 {h}" for h in _BLOCKED_HOSTS)
            await self.exec_as_root(
                environment,
                command=f'printf "%b\\n" {shlex.quote(entries)} >> /etc/hosts',
            )

        # Thomas is not published to PyPI, so install from source at a pinned
        # ref. --break-system-packages keeps this working on PEP668 images.
        src = "/installed-agent/thomas"
        await self.exec_as_root(
            environment,
            command=(
                "set -euo pipefail; "
                f"rm -rf {src}; "
                f"git clone --filter=blob:none {shlex.quote(self._repo_url)} {src}; "
                f"git -C {src} checkout --detach {shlex.quote(self._repo_ref)}; "
                f"python3 -m pip install --break-system-packages -q {src} "
                "|| python3 -m pip install -q " + src
            ),
            timeout_sec=1800,
        )

        if self._provider == _CODEX_PROVIDER:
            # sitecustomize is imported at interpreter startup, so the token
            # resolver is registered before the CLI builds its LLM client.
            await self.exec_as_root(environment, command=f"mkdir -p {_BRIDGE_DIR}")
            await environment.upload_file(
                Path(__file__).with_name("codex_bridge.py"),
                f"{_BRIDGE_DIR}/sitecustomize.py",
            )

        # Checked as the agent user, not root: run() executes as the agent user,
        # so a root-only console-script location would pass a root check here
        # and then fail at run time.
        await self.exec_as_agent(
            environment, command="command -v thomas >/dev/null 2>&1"
        )

    # -------------------------------------------------------------------- run

    async def _codex_access_token(self) -> str:
        """Mint a fresh Codex access token from the job-wide host broker.

        Broker failures are re-raised as Harbor error types so the retry policy
        can act on them: a transient token-endpoint fault is retryable, while a
        bad credential is not and should fail the job fast rather than repeat
        46 times.
        """
        from harbor_thomas.codex_broker import (
            CodexAuthError,
            CodexTransientError,
            get_broker,
        )

        # Read the host process environment directly, NOT self._get_env: its
        # first source is extra_env, i.e. Harbor's --ae, and the trial wraps
        # every exec in scoped_exec_env(agent.extra_env) at the highest
        # precedence (harbor/trial/trial.py:504,535,1453 ->
        # environments/base.py:416-432 -> docker.py:1156-1158). Anything passed
        # with --ae is therefore handed to the container, where the agent under
        # test runs as root with a shell and open egress. os.environ is not:
        # Harbor never forwards it. A refresh token mints access tokens
        # indefinitely and survives access-token rotation, so it must stay here.
        leaked = sorted(
            name
            for name in ("THOMAS_CODEX_REFRESH_TOKEN", "THOMAS_CODEX_ACCESS_TOKEN")
            if name in self._extra_env
        )
        if leaked:
            raise AgentAuthenticationError(
                f"{', '.join(leaked)} was passed with --ae, which injects it "
                "into the task container. Export it in the host shell instead; "
                "the adapter reads it from the host and keeps it there."
            )

        refresh_token = os.environ.get("THOMAS_CODEX_REFRESH_TOKEN", "").strip()
        access_token = os.environ.get("THOMAS_CODEX_ACCESS_TOKEN", "").strip()
        if not refresh_token and not access_token:
            raise AgentAuthenticationError(
                "The openai_codex provider needs THOMAS_CODEX_REFRESH_TOKEN "
                "(preferred) or THOMAS_CODEX_ACCESS_TOKEN exported in the host "
                "shell. Do not pass it with --ae; that injects it into the "
                "task container."
            )
        try:
            return await get_broker(refresh_token, access_token).access_token()
        except CodexAuthError as exc:
            raise AgentAuthenticationError(str(exc)) from None
        except CodexTransientError as exc:
            raise ApiConnectionClosedError(str(exc)) from None

    def _resolve_model_env(self) -> dict[str, str]:
        """Build the THOMAS_MODELS_* block for a single 'bench' profile.

        Thomas reads no vendor-standard variable (there is no OPENAI_API_KEY /
        ANTHROPIC_API_KEY fallback), so every field is set explicitly, and
        THOMAS_DEFAULT_MODEL is mandatory: once env overrides create a models
        table, the built-in defaults are skipped and an unset default_model
        fails config validation with exit 2.
        """
        provider = self._provider
        base_url = self._base_url or _DEFAULT_BASE_URLS.get(provider, "")

        env = {
            "THOMAS_DEFAULT_MODEL": "bench",
            "THOMAS_MODELS_BENCH_PROVIDER": provider,
        }

        # Env overrides build the models table themselves, which skips the
        # built-in profile block in thomas/core/config.py:793-800 -- so every
        # field that block would have set must be set here too. Omitting these
        # two silently falls back to ModelConfig's bare defaults (4096 /
        # 8192), a ~24x context reduction that thomas/agent/loop_core.py:190
        # applies without warning and config.validate() does not flag.
        env["THOMAS_MODELS_BENCH_MAX_TOKENS"] = str(self._max_tokens)
        env["THOMAS_MODELS_BENCH_CONTEXT_WINDOW"] = str(self._context_window)

        if provider != _CODEX_PROVIDER:
            env["THOMAS_MODELS_BENCH_API_KEY"] = (
                self._get_env("THOMAS_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
                or ""
            )
        if base_url:
            env["THOMAS_MODELS_BENCH_BASE_URL"] = base_url
        if self.model_name:
            env["THOMAS_MODELS_BENCH_MODEL"] = self.model_name
        if self._reasoning_effort:
            env["THOMAS_MODELS_BENCH_REASONING_EFFORT"] = self._reasoning_effort
        return env

    def _resolve_runtime_env(self) -> dict[str, str]:
        """Runtime flags Thomas needs to behave as an unattended agent."""
        return {
            # production mode force-disables the shell tool with no override,
            # which would leave the agent unable to run any command at all.
            "THOMAS_ENV": "development",
            "THOMAS_TOOLS_ALLOW_SHELL": "true",
            # Filesystem tools are confined to the sandbox root; task files live
            # outside any single project dir, so open it to the filesystem.
            "THOMAS_TOOLS_SANDBOX_ROOT": "/",
            # The updater otherwise runs `pip install --upgrade` mid-trial,
            # mutating the agent under test. Must stay off for a valid run.
            "THOMAS_NO_AUTO_UPDATE": "1",
            "THOMAS_OLLAMA_AUTOSTART": "0",
            # Deliberately OUTSIDE the trial log directory. Thomas fans this out
            # into chat logs and several SQLite stores (thomas/core/config.py
            # :203-237), and everything under the log dir is downloaded and
            # published with the submission. Harbor's own scrubber skips files
            # with a NUL byte in their first 8KiB, so a SQLite store there would
            # ship unredactable.
            "THOMAS_DATA_DIR": _DATA_DIR,
        }

    @override
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        """Run one Thomas session against the task instruction.

        Uses ``environment.exec`` rather than the raising ``exec_as_agent``
        helper, then re-raises selectively. Thomas exits non-zero in states that
        are normal for a long-horizon run (1 = agent error, including
        pass-budget exhaustion; 3 = interrupted); marking those errored would
        misreport a task the verifier may well have passed. Provider failures
        are different: Harbor drives retries off
        ``exception_info.exception_type`` (``trial/queue.py``), so swallowing
        them costs a trial that a retry would have recovered. Those are
        classified and re-raised; the verifier still runs either way
        (``trial/single_step.py:83-88``).
        """
        out_file = (self.environment_logs_dir / _OUTPUT_FILENAME).as_posix()
        run_log = (self.environment_logs_dir / _RUN_LOG_FILENAME).as_posix()

        env = {**self._resolve_runtime_env(), **self._resolve_model_env()}

        bridge_prelude = ""
        if self._provider == _CODEX_PROVIDER:
            # Mint a fresh access token per trial. The refresh token stays on
            # the host so a rotation is never stranded in a discarded container.
            env["THOMAS_CODEX_ACCESS_TOKEN"] = await self._codex_access_token()
            # Prepend rather than assign: the task image may set PYTHONPATH.
            bridge_prelude = (
                f'export PYTHONPATH="{_BRIDGE_DIR}'
                '${PYTHONPATH:+:$PYTHONPATH}"; '
            )

        # Pass the instruction through the environment rather than as a literal
        # in the command string, so quoting cannot break on it.
        instruction_var = "HARBOR_THOMAS_INSTRUCTION"
        env[instruction_var] = instruction

        # Container-side stop just inside the harness budget. Thomas has no
        # internal wall clock (its only cap is a 400-pass runaway guard), so
        # otherwise the harness cancels it mid-await and the trial is errored.
        # SIGINT lets Thomas run its exit-3 path rather than dying outright.
        # Note it does NOT preserve token accounting: the summary line is
        # printed inside the try block that KeyboardInterrupt unwinds
        # (thomas/cli/_commands_base.py:434-440, :645), so a run stopped here
        # reports no tokens. Only a run that finishes on its own does.
        prefix = ""
        if self._agent_timeout_sec is not None:
            budget = max(self._agent_timeout_sec - self._timeout_grace_sec, 1.0)
            prefix = f"timeout --signal=INT {int(budget)} "

        command = (
            # pipefail is essential: without it the exit status is tee's, so
            # every run would look successful regardless of what Thomas did.
            "set -o pipefail; "
            f"{bridge_prelude}"
            f'thomas_instruction="${instruction_var}"; '
            f"unset {instruction_var}; "
            f"mkdir -p {shlex.quote(self.environment_logs_dir.as_posix())}; "
            f"{prefix}thomas chat \"$thomas_instruction\" "
            f"--autonomy-level {self._autonomy_level} "
            f"--run-log {shlex.quote(run_log)} "
            f"2>&1 | stdbuf -oL tee {shlex.quote(out_file)}"
        )

        # Remembered so published artifacts can be scrubbed of them below. Every
        # provider is covered, not just codex: a non-codex run injects a live
        # provider API key as THOMAS_MODELS_BENCH_API_KEY.
        self._injected_secrets = {
            value
            for key in ("THOMAS_CODEX_ACCESS_TOKEN", "THOMAS_MODELS_BENCH_API_KEY")
            if (value := env.get(key, "")) and len(value) >= 8
        }

        result = await environment.exec(command=command, env=env)
        self._exit_code = result.return_code

        if result.return_code != 0:
            # Re-raise only provider/infrastructure failures, which Harbor can
            # retry. Thomas' own non-zero exits are left to the verifier.
            error = self._classify_exec_error(command, result)
            if isinstance(error, ApiError):
                # The classified message embeds the truncated transcript, and
                # Harbor copies it into result.json and exception.txt -- both
                # outside logs_dir, so the redactor below cannot reach them.
                # Scrub here, at the only point this adapter controls.
                raise type(error)(self._scrub(str(error))) from None

    # --------------------------------------------------------------- context

    def _scrub(self, text: str) -> str:
        """Replace every injected secret in ``text``."""
        for secret in sorted(self._injected_secrets, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED-CREDENTIAL]")
        return text

    def _redact_published_artifacts(self) -> None:
        """Scrub injected credentials from everything that ships publicly.

        The credentials are in the environment of an agent running with a shell,
        as root, at full autonomy, and everything under the trial log directory
        is published with the submission. A single ``env`` or
        ``cat /proc/self/environ`` would otherwise put a live credential in a
        public artifact.

        Walks the tree rather than naming files: Harbor publishes the whole
        directory, and Harbor's own scrubber cannot cover these values because
        they are minted at runtime and never appear in ``extra_env``. Should
        normally find nothing.
        """
        if not self._injected_secrets:
            return
        for path in sorted(self.logs_dir.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                raw = path.read_bytes()
                if b"\0" in raw[:8192]:
                    continue  # binary; a secret here cannot be safely rewritten
                original = raw.decode("utf-8", errors="replace")
                cleaned = self._scrub(original)
                if cleaned == original:
                    continue
                path.write_text(cleaned)
                self.logger.warning(
                    "Redacted a credential from %s before publication.",
                    path.relative_to(self.logs_dir),
                )
            except Exception:
                # Never leave a file holding a live credential to be published.
                self.logger.exception(
                    "Could not scrub %s; truncating it rather than publishing.",
                    path,
                )
                try:
                    path.write_text("[REMOVED: could not scrub credentials]\n")
                except Exception:
                    self.logger.exception("Could not truncate %s either.", path)

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        """Populate token usage and run metadata from the teed transcript.

        Every context field is set here, and run() deliberately sets none.
        Harbor only calls this hook when the context is still empty
        (``Trial._populate_agent_context`` returns early on
        ``not agent_result.is_empty()``), so writing anything to the context
        during run() would silently suppress all token accounting for the
        trial. The hook still runs after a timeout or a non-zero exit, because
        the trial syncs agent output in a ``finally`` block.
        """
        self._redact_published_artifacts()

        context.metadata = {
            "thomas_exit_code": self._exit_code,
            "thomas_autonomy_level": self._autonomy_level,
            "thomas_repo_ref": self._repo_ref,
        }

        transcript = self.logs_dir / _OUTPUT_FILENAME
        if not transcript.exists():
            return

        text = _ANSI_RE.sub("", transcript.read_text(errors="replace"))
        matches = _TOKENS_RE.findall(text)
        if not matches:
            return

        # Thomas prints one summary per run; take the last if a run retried.
        prompt_tokens, completion_tokens, _total = matches[-1]
        context.n_input_tokens = int(prompt_tokens)
        context.n_output_tokens = int(completion_tokens)
