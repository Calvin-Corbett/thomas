"""One long line from the Build runner must not kill the transcript reader.

`_drain` read the runner's stdout with `StreamReader.readline()`, whose default
limit is 64 KiB. A longer line (a full reasoning summary, a big tool result)
raises `ValueError`, which `_drain` did not catch: the reader died, nothing read
the pipe any more, the runner blocked on its next write, and the Build tab
showed "Working" indefinitely while the run never ended or recorded.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from thomas.server.routes.evolve_agent_runtime import _drain

_LONG = 200_000


async def _run_child(script: str, transcript: Path) -> bool:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    return await asyncio.wait_for(_drain(proc, transcript), timeout=60)


@pytest.mark.asyncio
async def test_a_line_longer_than_the_reader_limit_reaches_the_transcript(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.txt"
    script = f"import sys; sys.stdout.write('x' * {_LONG} + '\\n'); sys.stdout.write('after\\n')"

    confirmed = await _run_child(script, transcript)

    # The child's text-mode stdout writes CRLF on Windows.
    lines = transcript.read_bytes().replace(b"\r\n", b"\n").split(b"\n")
    assert confirmed is True
    assert lines[0] == b"x" * _LONG
    assert lines[1] == b"after"


@pytest.mark.asyncio
async def test_output_after_a_long_line_keeps_flowing(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.txt"
    # Enough output after the long line to fill a pipe if nobody were reading it.
    script = (
        "import sys\n"
        f"sys.stdout.write('y' * {_LONG} + '\\n')\n"
        "for i in range(20000):\n"
        "    sys.stdout.write('line %d\\n' % i)\n"
    )

    confirmed = await _run_child(script, transcript)

    text = transcript.read_text(encoding="utf-8")
    assert confirmed is True
    assert text.rstrip("\n").endswith("line 19999")
