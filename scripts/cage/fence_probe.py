"""Check the network fence from the cage account's own side.

Runs three connections as thomas-agent, through the caged shell, and says whether
each ended the way the fence requires:

* direct, around the proxy, to a host on the internet: no connection at all;
* through the proxy, to a host that is not pinned: refused (403);
* through the proxy, to a pinned model host: connected.

enable_network_fence.ps1 runs it before adding the firewall rule (the direct
connection must work then, or a later failure proves nothing) and after it, and
takes the rule out again if the fence does not hold. It can be rerun at any time;
it changes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.cage.egress_proxy import PORT  # noqa: E402

PROXY = f"http://127.0.0.1:{PORT}"
PROBES = {
    "direct": 'curl.exe --noproxy "*" -s -o NUL --max-time 10 -w "%{http_code}" https://example.com',
    "unlisted": f'curl.exe -s -o NUL --max-time 10 -w "%{{http_connect}}" -x {PROXY} https://example.com',
    "listed": f'curl.exe -s -o NUL --max-time 15 -w "%{{http_connect}}" -x {PROXY} https://chatgpt.com',
}


def probe(repo: Path) -> dict[str, str]:
    from thomas.tools.cage_shell import run_caged

    results = {}
    for name, command in PROBES.items():
        done = run_caged(command, cwd=str(repo), timeout_s=40.0)
        results[name] = (done.output or "").strip() or f"({done.outcome})"
    return results


def problems(results: dict[str, str], *, fenced: bool) -> list[str]:
    """What is wrong with *results* for a cage that is (or is not yet) fenced."""
    found = []
    direct = results.get("direct", "")
    if fenced and direct != "000":
        found.append(f"a direct connection from the cage still worked (HTTP {direct})")
    if not fenced and direct in {"", "000"}:
        found.append("the cage could not connect directly even before the fence, so a test after it proves nothing")
    if results.get("unlisted") != "403":
        found.append(f"the proxy did not refuse an unpinned host (got {results.get('unlisted')!r})")
    if results.get("listed") != "200":
        found.append(f"the proxy did not connect a pinned model host (got {results.get('listed')!r})")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the cage's network fence from the cage's side.")
    parser.add_argument("--fenced", action="store_true", help="the firewall rule is in place")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args(argv)
    results = probe(Path(args.repo))
    found = problems(results, fenced=args.fenced)
    print(json.dumps({"results": results, "problems": found}))
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
