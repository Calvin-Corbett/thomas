"""Async ReAct agent loop with streaming, parallel tools, and context management.

The core execution engine for Thomas. Handles:
- Streaming LLM responses to the caller in real-time
- Parallel tool execution when tools are independent
- Context window tracking and overflow prevention via token counting
- Automatic conversation trimming when approaching context limits
- Configurable iteration limits with stop conditions
- Error recovery with retries and graceful degradation
- Memory context injection

This is a thin facade that delegates to specialized modules:
- loop_core: Message building, initialization, routing helpers
- loop_tools: Tool selection and execution
- loop_streaming: Memory, library, token management
- loop_planning: Response sanitization, nudging, and the main run() loop
"""

from __future__ import annotations

import ast
import inspect
import ipaddress
import logging
import os
import re
import ssl
import textwrap
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from thomas.agent.response_tone import (
    best_practice_default_hint,
    best_practice_gate_hint,
    live_test_default_hint,
    prompt_requests_code_output,
    simplified_review_default_hint,
)
from thomas.agent.skills_runtime import (
    format_runtime_skills_context,
    resolve_runtime_skills,
)
from thomas.core.autonomy import autonomy_spec
from thomas.core.config import load_config
from thomas.core.events import AgentEvent, EventType
from thomas.core.llm import LLMError
from thomas.core.rules_of_road import build_remediation_prompt, evaluate_rules
from thomas.core.token_economy import (
    build_token_economy_meta,
    loop_context_budgets,
    loop_iteration_prompt_caps,
    loop_tool_spec_budgets,
    normalize_token_economy_level,
)
from thomas.core.tokens import estimate_tokens, estimate_tools_tokens

try:
    from thomas.agent.context_compaction import compact_conversation, should_compact

    _HAS_COMPACTION = True
except ImportError:
    _HAS_COMPACTION = False

# Import from new modules
from thomas.agent.loop_core import AgentLoop as _AgentLoopBase
from thomas.agent.loop_core import LoopState
from thomas.agent.loop_planning import (
    assume_and_proceed_nudge,
    full_auto_nudge,
    looks_like_clarifying_question,
    routing_input_text,
    sanitize_assistant_text,
)
from thomas.agent.loop_streaming import (
    apply_memory_policy,
    auto_capture_research,
    build_token_report,
    capture_profile_hints,
    input_continuity_hint,
    normalize_usage,
    record_event,
    retrieve_library,
    retrieve_memory,
    session_usage_snapshot,
    usage_delta,
    usage_from_event_payload,
)
from thomas.agent.loop_tools import execute_tools, parse_tool_args, select_tools

if TYPE_CHECKING:
    from thomas.agent.routing import RouteDecision

log = logging.getLogger(__name__)

_MAX_TOOL_RESULT_CHARS = 5_000
_TPM_WINDOW_SECONDS = 60.0
_TPM_MAX_AUTO_WAIT_S = 20.0


async def _coerce_async_iterator(value: Any, *, source: str) -> AsyncIterator[Any]:
    try:
        return aiter(value)
    except TypeError as exc:
        if inspect.isawaitable(value):
            try:
                resolved = await value
            except Exception as await_exc:
                log.exception("Failed to resolve awaitable async iterator source %s", source)
                raise TypeError(
                    f"{source} returned awaitable that failed to resolve: {type(await_exc).__name__}: {await_exc}"
                ) from await_exc
            try:
                return aiter(resolved)
            except TypeError as resolved_exc:
                raise TypeError(
                    f"{source} returned {type(resolved)!r} after await, not an async iterator."
                ) from resolved_exc
        raise TypeError(f"{source} returned unsupported type {type(value)!r}; expected async iterator.") from exc


def _extract_benchmark_context(prompt_text: str) -> tuple[str, str]:
    """Extract probable code context and explicit entry-point from a benchmark prompt."""
    src = str(prompt_text or "")
    if not src.strip():
        return "", ""

    entry_point = ""
    entry_match = re.search(r"(?im)^.*\bentry\s*point\s*:\s*([A-Za-z_][A-Za-z0-9_]*)", src)
    if entry_match:
        entry_point = str(entry_match.group(1) or "").strip()

    marker_match = re.search(
        r"(?is)---\s*prompt\s*start\s*---(.*?)---\s*prompt\s*end\s*---",
        src,
    )
    if marker_match:
        return str(marker_match.group(1) or "").strip(), entry_point

    lines = src.splitlines()
    block: list[str] = []
    block_indent = 0
    for line in lines:
        if re.match(r"^\s*(?:def|class)\s+[A-Za-z_][A-Za-z0-9_]*\b", line):
            block = [line.rstrip()]
            block_indent = len(line) - len(line.lstrip())
            continue
        if block:
            if line.strip() == "":
                block.append("")
                continue
            line_indent = len(line) - len(line.lstrip())
            if line_indent <= block_indent:
                break
            block.append(line.rstrip())
    if block:
        return "\n".join(block).strip(), entry_point
    return "", entry_point


def _benchmark_continuation_has_non_trivial_body(continuation: str) -> tuple[bool, str]:
    """Return whether continuation body is non-trivial for benchmark prompts."""
    body_text = textwrap.dedent(str(continuation or ""))
    if not body_text.strip():
        return False, "empty continuation body"

    probe_source = "def __thomas_benchmark_probe__():\n" + textwrap.indent(body_text, "    ")
    try:
        probe_tree = ast.parse(probe_source)
    except SyntaxError as exc:
        return False, f"code-body parse error: {exc.msg}"

    probe_func = probe_tree.body[0] if probe_tree.body else None
    if not isinstance(probe_func, ast.FunctionDef):
        return False, "benchmark continuation structure invalid"
    probe_body = list(probe_func.body)
    if not probe_body:
        return False, "no benchmark continuation statements"

    meaningful = [
        n
        for n in probe_body
        if not (
            isinstance(n, ast.Pass)
            or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))
        )
    ]
    if not meaningful:
        return False, "continuation is only a placeholder/trivial stub"
    return True, ""


def _validate_benchmark_code_output(
    *,
    prompt_text: str,
    continuation: str,
) -> tuple[bool, str, str]:
    """Validate that benchmark output is valid and non-trivial continuation code."""
    context_text, entry_point = _extract_benchmark_context(prompt_text)
    candidate = str(continuation or "")
    if not candidate.strip():
        issue = "empty benchmark code output"
        if entry_point:
            issue = f"{issue} for entry point '{entry_point}'"
        return False, issue, entry_point

    context = context_text.strip()
    combined = (context + ("\n" if context else "")) + candidate
    compile_ok = False
    compile_issue = ""
    try:
        compile(combined, "<benchmark>", "exec")
        compile_ok = True
    except SyntaxError as exc:
        compile_issue = f"benchmark code syntax error: {exc.msg}"

    if not compile_ok:
        # Retry as a function-body candidate.
        indented = candidate
        if not re.match(r"^\\s+[A-Za-z_#\\n]", candidate or "", flags=re.M):
            # not obviously body-like; leave as-is
            indented = textwrap.indent(textwrap.dedent(candidate), "    ")
        try:
            compile("def __thomas_benchmark_probe__():\n" + indented, "<benchmark>", "exec")
            compile_ok = True
        except SyntaxError as exc:
            issue = f"{compile_issue or 'invalid'}; {exc.msg}"
            if entry_point:
                issue = (
                    issue + f" (expected a working continuation for entry point '{entry_point}' and no explanations)."
                )
            return False, issue, entry_point

    has_non_trivial, reason = _benchmark_continuation_has_non_trivial_body(candidate)
    if not has_non_trivial:
        issue = reason
        if entry_point:
            issue = (
                f"{issue} (expected a non-trivial continuation for entry point '{entry_point}'," " avoid no-op stubs)"
            )
        return False, issue, entry_point

    if not prompt_requests_code_output(prompt_text):
        return False, "prompt did not request benchmark code output", entry_point

    return True, "", entry_point


# Sentinel for catching connection errors without importing httpx at module level
try:
    import httpx as _httpx

    httpx_ConnectError = _httpx.ConnectError
except ImportError:
    _httpx = None  # type: ignore[assignment]
    httpx_ConnectError = OSError  # type: ignore[misc,assignment]


def _coerce_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "y", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "n", "disabled"}:
        return False
    return default


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.strip().strip("[]")
    if host.lower() in {"localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _build_min_tls_ssl_context() -> Any:
    ca_path = os.environ.get("THOMAS_OUTBOUND_CA_BUNDLE")
    if ca_path:
        ca_file = str(Path(ca_path).expanduser())
        if not Path(ca_file).is_file():
            raise LLMError(f"Configured THOMAS_OUTBOUND_CA_BUNDLE not found: {ca_file}")
        context = ssl.create_default_context(cafile=ca_file)
    else:
        context = ssl.create_default_context()

    try:
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    except AttributeError:
        if hasattr(ssl, "OP_NO_SSLv3"):
            context.options |= ssl.OP_NO_SSLv3  # type: ignore[attr-defined]
        if hasattr(ssl, "OP_NO_TLSv1"):
            context.options |= ssl.OP_NO_TLSv1  # type: ignore[attr-defined]
        if hasattr(ssl, "OP_NO_TLSv1_1"):
            context.options |= ssl.OP_NO_TLSv1_1  # type: ignore[attr-defined]
    return context


async def _ensure_llm_hardened_client(llm: Any) -> None:
    if _httpx is None:
        return

    provider = str(getattr(llm.config, "provider", "") or "").lower()
    if provider == "codex":
        return

    base_url = str(getattr(llm.config, "base_url", "") or "").strip()
    if not base_url:
        return
    parsed = urlparse(base_url)
    scheme = (parsed.scheme or "").lower()
    if scheme and scheme not in {"http", "https"}:
        raise LLMError(f"Unsupported LLM base_url scheme '{parsed.scheme}' in '{base_url}'. Use http:// or https://")
    if scheme == "http" and not _is_loopback_host(parsed.hostname):
        raise LLMError(
            "Outbound LLM calls require HTTPS for non-loopback hosts. "
            f"Configure '{base_url}' with https:// or a loopback address."
        )
    if scheme != "https":
        return

    verify_tls = _coerce_bool(os.environ.get("THOMAS_OUTBOUND_VERIFY_TLS"), True)
    if not verify_tls:
        raise LLMError(
            "TLS certificate verification is disabled via THOMAS_OUTBOUND_VERIFY_TLS=false, "
            "but outbound TLS verification is required."
        )

    if getattr(llm, "_thomas_tls_hardened_base_url", None) == base_url:
        existing_client = getattr(llm, "_client", None)
        if existing_client is not None and not existing_client.is_closed:
            return

    headers = {"Content-Type": "application/json"}
    if getattr(llm.config, "extra_headers", None):
        headers.update(llm.config.extra_headers)

    if llm.config.api_key:
        if provider == "anthropic":
            headers["x-api-key"] = str(llm.config.api_key)
            headers.setdefault("anthropic-version", "2023-06-01")
        else:
            header_name = llm.config.api_key_header or "Authorization"
            prefix = llm.config.api_key_prefix or ""
            headers[header_name] = f"{prefix}{llm.config.api_key}"

    existing_client = getattr(llm, "_client", None)
    if existing_client is not None and not existing_client.is_closed:
        await existing_client.aclose()

    llm._client = _httpx.AsyncClient(
        headers=headers,
        timeout=_httpx.Timeout(
            connect=10.0,
            read=float(getattr(llm.config, "timeout_s", 120.0)),
            write=10.0,
            pool=10.0,
        ),
        verify=_build_min_tls_ssl_context(),
    )
    llm._thomas_tls_hardened_base_url = base_url
