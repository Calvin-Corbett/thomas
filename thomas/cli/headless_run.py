"""Run a headless Thomas chat with every sign-in the server would have.

``python -m thomas chat <goal>`` cannot use the ChatGPT sign-in: the only
place that registers the token resolver the core transport needs is the
server's OAuth module, which the CLI never imports (found 2026-09-05 when a
scheduled task fired and died with "ChatGPT OAuth is not connected"). This
entry imports that module first, then runs the same ``chat`` command:

    python -m thomas.cli.headless_run "Reply with the word pong"
    python -m thomas.cli.headless_run --json "Reply with the word pong"   # one JSON line on stdout

The scheduler's executor uses it. It is the CLI importing the server, which
the architecture allows; the core transport still imports neither.
"""

from __future__ import annotations

import io
import json
import logging
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DECORATION = re.compile(r"\[(?:route [^\]]*|iteration \d+|calling [^\]]*\.\.\.)\] ?")


_VERIFICATION = re.compile(r"^Verification: (\d+)/(\d+) checks passed\.$")
_TOKENS = re.compile(r"^\[tokens: (\d+) prompt \+ (\d+) completion = (\d+) total\]$")
_RUNTIME = re.compile(r"^\[runtime model: ([^\]]+)\]$")
# The CLI's tool trace ("[shell.exec: failed 78ms]" then an optional JSON line),
# the done footer's check lists and its "(5 iterations, 4 tool calls)" line.
_TOOL_LINE = re.compile(r"^\[([A-Za-z0-9_.]+): (ok|failed) (\d+)ms\]$")
_COUNTS = re.compile(r"^\((\d+) iterations?, (\d+) tool calls?\)$")
_CHECK_BLOCK = re.compile(r"^(Verified|Unchecked)\b.*:$")


def strip_decorations(captured: str) -> str:
    """The reply as the person would read it: no colour codes, no route/iteration/tool notes."""
    return split_summary(captured)["reply"]


def split_summary(captured: str) -> dict[str, Any]:
    """The reply text, and the CLI's closing summary lines as fields.

    A real run put "Verification: 2/2 checks passed.", the token line and the
    runtime line inside the reply; a script wants them as data.
    """
    text = _DECORATION.sub("", _ANSI.sub("", str(captured or "")))
    out: dict[str, Any] = {
        "verification": None,
        "tokens": None,
        "runtime_model": "",
        "tool_log": [],
        "checks": None,
        "iterations": None,
        "tool_calls": None,
    }
    kept: list[str] = []
    block = ""  # "verified" | "unchecked" while inside the done footer's check lists
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if m := _TOOL_LINE.match(stripped):
            out["tool_log"].append(
                {"tool": m.group(1), "ok": m.group(2) == "ok", "ms": int(m.group(3)), "detail": None}
            )
            block = ""
        elif (
            out["tool_log"]
            and out["tool_log"][-1]["detail"] is None
            and stripped.startswith("{")
            and _is_json(stripped)
        ):
            out["tool_log"][-1]["detail"] = json.loads(stripped)
        elif m := _VERIFICATION.match(stripped):
            out["verification"] = {"passed": int(m.group(1)), "total": int(m.group(2))}
        elif m := _TOKENS.match(stripped):
            out["tokens"] = {"prompt": int(m.group(1)), "completion": int(m.group(2)), "total": int(m.group(3))}
        elif m := _RUNTIME.match(stripped):
            out["runtime_model"] = m.group(1).strip()
        elif m := _COUNTS.match(stripped):
            out["iterations"], out["tool_calls"] = int(m.group(1)), int(m.group(2))
            block = ""
        elif m := _CHECK_BLOCK.match(stripped):
            block = m.group(1).lower()
            out["checks"] = out["checks"] or {"verified": [], "unchecked": []}
        elif block and stripped.startswith("- "):
            out["checks"][block].append(stripped[2:].strip())
        else:
            block = ""
            kept.append(line)
    out["reply"] = "\n".join(kept).strip()
    return out


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def json_result(*, captured: str, record: dict[str, Any] | None, exit_code: int) -> str:
    """One JSON line: the reply plus the run-log record's outcome and model, and the exit code."""
    rec = record if isinstance(record, dict) else {}
    parts = split_summary(captured)
    return json.dumps(
        {
            "ok": int(exit_code) == 0,
            "exit_code": int(exit_code),
            "outcome": str(rec.get("outcome") or ""),
            "model_profile": str(rec.get("model_profile") or ""),
            "model": str(rec.get("model") or ""),
            "duration_s": rec.get("duration_s"),
            "reply": parts["reply"],
            "verification": parts["verification"],
            "tokens": parts["tokens"],
            "runtime_model": parts["runtime_model"],
            "tool_log": parts["tool_log"],
            "checks": parts["checks"],
            "iterations": parts["iterations"],
            "tool_calls": parts["tool_calls"],
            "error": str(rec.get("error") or ""),
            "artifacts": list(rec.get("artifacts") or []),
        },
        ensure_ascii=False,
    )


def split_json_flag(args: list[str]) -> tuple[bool, list[str]]:
    """``--json`` is this entry's flag, not the chat command's; take it out of the way."""
    wanted = "--json" in args
    return wanted, [a for a in args if a != "--json"]


def _last_record(path: Path) -> dict[str, Any] | None:
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return json.loads(lines[-1]) if lines else None
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> None:
    import thomas.server.openai_codex_oauth  # noqa: F401  registers the ChatGPT token resolver
    from thomas.cli.main import cli

    as_json, args = split_json_flag(list(sys.argv[1:] if argv is None else argv))
    # On a terminal, an ask_user question is printed and answered here; a
    # scheduled run has no terminal, so the tool's timeout applies instead.
    from thomas.cli.ask_user_console import start_console_answerer

    if not as_json:
        sys.argv = [sys.argv[0] if sys.argv else "thomas", "chat", *args]
        start_console_answerer()
        cli(obj={})
        return

    # JSON mode (frontier parity: claude -p --output-format json, codex exec
    # --json): the chat streams to a buffer, the run log names the outcome and
    # model, and stdout gets exactly one line. The console answerer stays off:
    # a JSON caller is a script, not a person at a terminal.
    with tempfile.TemporaryDirectory() as tmp:
        run_log = Path(tmp) / "run.jsonl"
        sys.argv = [sys.argv[0] if sys.argv else "thomas", "chat", "--run-log", str(run_log), *args]
        buffer = io.StringIO()
        real_stdout, sys.stdout = sys.stdout, buffer
        exit_code = 0
        try:
            cli(obj={}, standalone_mode=False)
        except SystemExit as exc:
            exit_code = int(exc.code or 0) if isinstance(exc.code, int) or exc.code is None else 1
        except (ConnectionError, OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
            log.exception("headless JSON chat failed")
            exit_code = 1
            buffer.write(f"\n{type(exc).__name__}: {exc}")
        finally:
            sys.stdout = real_stdout
        record = _last_record(run_log)
        sys.stdout.write(json_result(captured=buffer.getvalue(), record=record, exit_code=exit_code) + "\n")
        sys.stdout.flush()
    raise SystemExit(exit_code)


# Registering on import lets any process that imports this module use the
# sign-in, not only the ``python -m`` entry. The explicit call covers a
# server module that was already loaded before the slot was cleared.
from thomas.core import codex_auth as _codex_auth  # noqa: E402
from thomas.server import openai_codex_oauth as _oauth  # noqa: E402

if _codex_auth._access_token_resolver is None:
    _codex_auth.register_access_token_resolver(_oauth._resolve_registered_access_token)

if __name__ == "__main__":
    main()
