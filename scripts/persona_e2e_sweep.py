"""End-to-end persona sweep — drive the REAL chat backend for all 120 persona tasks.

For each (persona, task) this POSTs to /api/v2/chat (the real pipeline), streams the
NDJSON response, and records per-task: first-text latency (instant check), full reply,
total elapsed, dispatch/card events, and the card title (via the real titlers). Then it
checks the rubric invariants Calvin named:
  * no canned reply  * no instantaneous reply  * card title names the task
This is the scaled, end-to-end version of "run 20 complex tasks per persona and look at
the card + elapsed + end result" — at the API level (reliable) for throughput.

Usage: python scripts/persona_e2e_sweep.py [port] [limit_per_persona]
"""

from __future__ import annotations

import http.client
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.persona_validation_sweep import PERSONAS  # noqa: E402
from thomas.core.task_titling import derive_task_title  # noqa: E402
from thomas.marketplace.observability.task_ledger import derive_active_goal  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8903
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 20  # tasks per persona

# Canned phrases that must NEVER appear as a whole reply (the removed auto-acks).
_CANNED = ("on it.", "working on that", "i've handed that to the task manager", "got it. i've kicked")
_FILLER_PREFIX = ("help me", "i'm ", "i am ", "can you", "could you", "please ", "i want", "i need", "i'd like")


def _stream_chat(task: str, sid: str) -> dict:
    payload = json.dumps(
        {
            "session_id": sid,
            "profile": "local",
            "autonomy_level": 3,
            "mode": "auto",
            "message": task,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/v2/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    first_text_at = None
    reply_parts: list[str] = []
    event_types: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue  # a non-JSON keepalive/framing line: skip it
                et = str(evt.get("type") or "")
                event_types.append(et)
                chunk = evt.get("text") or evt.get("delta") or evt.get("content")
                if et in ("text", "token", "delta") and isinstance(chunk, str) and chunk.strip():
                    if first_text_at is None:
                        first_text_at = time.monotonic() - t0
                    reply_parts.append(chunk)
    # Per-case error boundary: one unreachable/slow/half-streamed case must be
    # recorded and the sweep must continue, so this degrade is load-bearing.
    # urllib's URLError/HTTPError and socket timeouts are OSError; a truncated
    # chunked body is http.client.HTTPException; ValueError covers a bad URL and
    # json.JSONDecodeError (a ValueError subclass) a malformed event.
    except (OSError, http.client.HTTPException, ValueError, TypeError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "elapsed_s": round(time.monotonic() - t0, 2)}
    return {
        "reply": "".join(reply_parts).strip(),
        "first_text_latency_s": round(first_text_at, 2) if first_text_at is not None else None,
        "elapsed_s": round(time.monotonic() - t0, 2),
        "dispatched": any(e in ("delegation_started", "task_dispatched", "delegation") for e in event_types),
    }


def main() -> None:
    rows = []
    n = 0
    for persona, tasks in PERSONAS.items():
        for i, task in enumerate(tasks[:LIMIT]):
            n += 1
            sid = f"sweep-{persona}-{i}-{int(time.time())}"
            res = _stream_chat(task, sid)
            # card titles from the real titlers (all three surfaces)
            chat_title = derive_active_goal(task, current_goal="")
            office_title = derive_task_title(task)
            reply = res.get("reply", "")
            low = reply.lower().strip()
            row = {
                "n": n,
                "persona": persona,
                "task": task[:70],
                "chat_card_title": chat_title,
                "office_card_title": office_title,
                "first_text_latency_s": res.get("first_text_latency_s"),
                "elapsed_s": res.get("elapsed_s"),
                "dispatched": res.get("dispatched"),
                "reply_len": len(reply),
                "error": res.get("error"),
                # rubric checks
                "FAIL_canned": any(c in low for c in _CANNED),
                "FAIL_instant": (res.get("first_text_latency_s") is not None and res["first_text_latency_s"] < 0.5),
                "FAIL_empty": (not reply and not res.get("error")),
                "FAIL_title_filler": chat_title.lower().startswith(_FILLER_PREFIX)
                or office_title.lower().startswith(_FILLER_PREFIX),
                "reply_preview": reply[:120],
            }
            rows.append(row)
            flags = [k for k in ("FAIL_canned", "FAIL_instant", "FAIL_empty", "FAIL_title_filler") if row[k]]
            print(
                f"[{n:3}/{LIMIT * len(PERSONAS)}] {persona:16} {res.get('elapsed_s')}s "
                f"lat={res.get('first_text_latency_s')} disp={res.get('dispatched')} "
                f"{'ERR:' + res['error'] if res.get('error') else ('FAIL:' + ','.join(flags) if flags else 'ok')} "
                f"| card={chat_title[:40]!r}",
                flush=True,
            )
    summary = {
        "total": len(rows),
        "errors": sum(1 for r in rows if r["error"]),
        "FAIL_canned": sum(1 for r in rows if r["FAIL_canned"]),
        "FAIL_instant": sum(1 for r in rows if r["FAIL_instant"]),
        "FAIL_empty": sum(1 for r in rows if r["FAIL_empty"]),
        "FAIL_title_filler": sum(1 for r in rows if r["FAIL_title_filler"]),
        "median_elapsed_s": sorted(r["elapsed_s"] for r in rows if r["elapsed_s"])[len(rows) // 2] if rows else 0,
    }
    out = ROOT / "persona_e2e_results.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
