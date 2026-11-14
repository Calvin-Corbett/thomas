"""Run CPU/file parsers in a cancellable, output-bounded Python child process."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class WorkerFailure(RuntimeError):
    """A worker failed, exceeded its budget, or returned invalid output."""


async def _reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


async def run_json_worker(
    module: str, payload: dict[str, Any], *, timeout: float = 6.0, max_output: int = 400_000
) -> dict[str, Any]:
    """Kill and reap the child on timeout, cancellation, or excess output.

    The module is an internal constant, never a user-supplied command. Pin its
    import root to this running package, even when the tool's workspace differs.
    No shell or temporary user files are involved.
    """
    data = json.dumps(payload, ensure_ascii=True).encode()
    if len(data) > 8_000_000:
        raise WorkerFailure("Worker input exceeds the 8 MB limit")
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [package_root, env.get("PYTHONPATH", "")]))
    env["PYTHONIOENCODING"] = "utf-8"
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            module,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            cwd=package_root,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    )
    try:
        process = await asyncio.shield(spawn)
    except asyncio.CancelledError:
        # Cancellation during process creation must not strand a late child.
        await _reap(await spawn)
        raise
    except OSError as exc:
        raise WorkerFailure(f"Could not start document/search worker: {exc}") from exc

    async def exchange() -> bytes:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(data)
        await process.stdin.drain()
        process.stdin.close()
        chunks: list[bytes] = []
        size = 0
        while chunk := await process.stdout.read(min(65_536, max_output + 1 - size)):
            size += len(chunk)
            if size > max_output:
                raise WorkerFailure("Worker output limit exceeded; result is incomplete")
            chunks.append(chunk)
        await process.wait()
        if process.returncode != 0:
            raise WorkerFailure("Document/search worker failed; no complete result is available")
        return b"".join(chunks)

    try:
        output = await asyncio.wait_for(exchange(), timeout=timeout)
        result = json.loads(output)
        if not isinstance(result, dict):
            raise WorkerFailure("Worker returned an invalid result")
        return result
    except asyncio.TimeoutError as exc:
        raise WorkerFailure(
            f"Execution deadline exceeded ({timeout:g}s); worker stopped. "
            "Result is incomplete; inspected/skipped counts are unavailable."
        ) from exc
    except (ValueError, BrokenPipeError, ConnectionResetError) as exc:
        raise WorkerFailure("Worker returned unreadable or incomplete output") from exc
    finally:
        await asyncio.shield(_reap(process))
