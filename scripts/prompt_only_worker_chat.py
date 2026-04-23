from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from thomas.demo.project_swarm_runner import _make_llm_client, _make_prompt_only_worker_llm_client


async def _run(args: argparse.Namespace) -> int:
    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    output_path = Path(args.output_file)
    namespace = SimpleNamespace(config=args.config or None, profile=args.profile or None)
    client = _make_prompt_only_worker_llm_client(namespace) if str(args.mode or "structured") == "worker" else _make_llm_client(namespace)
    config = getattr(client, "config", None)
    if config is not None:
        updates = {}
        if getattr(args, "request_timeout_s", None) is not None:
            updates["timeout_s"] = float(args.request_timeout_s)
        if getattr(args, "max_tokens", None) is not None:
            updates["max_tokens"] = int(args.max_tokens)
        if getattr(args, "reasoning_effort", None):
            updates["reasoning_effort"] = str(args.reasoning_effort).strip()
        if updates:
            adjusted = replace(config, **updates)
            client.config = adjusted
            if getattr(client, "_primary_config", None) is config:
                client._primary_config = adjusted
    try:
        response = await client.chat(
            [
                {"role": "system", "content": str(args.system_prompt or "").strip()},
                {"role": "user", "content": prompt},
            ]
        )
    finally:
        await client.close()
    output_path.write_text(str(response.get("text") or ""), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one prompt-only worker chat request and write the raw text output.")
    parser.add_argument("--mode", choices=["worker", "structured"], default="structured")
    parser.add_argument("--system-prompt", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--config")
    parser.add_argument("--profile")
    parser.add_argument("--request-timeout-s", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--reasoning-effort", default=None)
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
