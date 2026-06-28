"""CLI-backed ``ModelCall`` implementations for headless funnel runs.

The funnel's default ``DefaultModelCall`` uses the in-process ``LLMClient``, which
needs the provider OAuth token in the secret store. In a headless context (a
server started outside Easy Setup, CI, a sandbox) that token may not be reachable
even though the operator is authenticated through an agent CLI. These backends let
the funnel run anyway by shelling out to an already-authenticated CLI:

- ``ClaudeCliModelCall`` -> ``claude -p`` (clean completion on stdout). Lane backend.
- ``CodexExecModelCall`` -> ``codex exec -o <file>`` (final message). A genuinely
  DIFFERENT model family (GPT) -- ideal for the cross-family external evaluator.

Each call is a fresh subprocess, so the funnel's "fresh / one-shot / memoryless"
lane contract holds by construction. Both fail soft (return "") so a dead call
degrades to a dropped lane rather than crashing the stage.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


def _compose(system: str, user: str) -> str:
    s, u = (system or "").strip(), (user or "").strip()
    return f"{s}\n\n{u}".strip() if s else u


class ClaudeCliModelCall:
    """One-shot completion via ``claude -p`` (Claude family). Lane/synth backend."""

    def __init__(self, model: str = "sonnet", timeout: int = 240) -> None:
        self.model = model
        self.timeout = timeout

    def __call__(self, system: str, user: str, profile: str = "") -> str:
        try:
            proc = subprocess.run(
                ["claude", "-p", "--model", self.model, _compose(system, user)],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            return ""
        return (proc.stdout or "").strip()


class CodexExecModelCall:
    """One-shot completion via ``codex exec`` (GPT family) -> cross-family evaluator.

    Lean flags: read-only sandbox (lanes only produce text), MCP disabled and low
    reasoning effort (cost/latency), final message captured via ``-o`` so the
    output is the model's answer with no session chrome to parse.
    """

    def __init__(self, timeout: int = 300, reasoning: str = "low") -> None:
        self.timeout = timeout
        self.reasoning = reasoning

    def __call__(self, system: str, user: str, profile: str = "") -> str:
        fd, out_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            subprocess.run(
                [
                    "codex",
                    "exec",
                    "-s",
                    "read-only",
                    "-c",
                    "mcp_servers={}",
                    "-c",
                    f'model_reasoning_effort="{self.reasoning}"',
                    "-o",
                    out_path,
                    _compose(system, user),
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            return ""
        finally:
            text = ""
            try:
                text = Path(out_path).read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                text = ""
            try:
                os.unlink(out_path)
            except OSError:
                pass
        return text
