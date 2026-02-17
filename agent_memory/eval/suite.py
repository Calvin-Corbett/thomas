from __future__ import annotations
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple

from agent_memory.app import AgentMemoryApp

@dataclass
class EvalResult:
    name: str
    passed: bool
    details: str

def _plant(app: AgentMemoryApp, thread: str, n: int) -> List[int]:
    ids = []
    for i in range(n):
        ids.append(app.log_event(thread=thread, etype="note", text=f"filler {i} lorem ipsum some unrelated content"))
    return ids

def needle_test(app: AgentMemoryApp, thread: str) -> EvalResult:
    _plant(app, thread, 120)
    needle = "the password is Blueberry42 and the server is named NIMBUS"
    nid = app.log_event(thread=thread, etype="note", text=f"IMPORTANT {needle}")
    _plant(app, thread, 120)
    out = app.query(thread=thread, mode="deep", text="what was the password and server name i mentioned earlier")
    packed = out["packed"]
    ok = ("Blueberry42" in packed) and ("NIMBUS" in packed)
    return EvalResult("needle", ok, f"found={ok} selected={out['selected'][:5]}")

def temporal_contradiction_test(app: AgentMemoryApp, thread: str) -> EvalResult:
    app.log_event(thread=thread, etype="note", text="I like blue for UI accents")
    _plant(app, thread, 40)
    app.log_event(thread=thread, etype="note", text="I hate blue now, use green instead")
    out = app.query(thread=thread, mode="deep", text="what color should i use for UI accents")
    packed = out["packed"].lower()
    ok = ("hate blue" in packed) or ("use green" in packed) or ("green" in packed)
    return EvalResult("temporal_contradiction", ok, "expects latest preference dominates")

def mode_stability_test(app: AgentMemoryApp, thread: str) -> EvalResult:
    app.log_event(thread=thread, etype="note", text="coding preference: python 3.12, type hints, boring stable solutions")
    _plant(app, thread, 30)
    out1 = app.query(thread=thread, mode="fast", text="what are my coding preferences")
    out2 = app.query(thread=thread, mode="deep", text="what are my coding preferences")
    ok = ("python 3.12" in out1["packed"].lower()) or ("python" in out1["packed"].lower())
    ok2 = ("python 3.12" in out2["packed"].lower()) or ("type hints" in out2["packed"].lower())
    return EvalResult("mode_stability", bool(ok and ok2), "fast and deep both should surface core preferences")

def latency_smoke_test(app: AgentMemoryApp, thread: str) -> EvalResult:
    t0 = time.time()
    _ = app.query(thread=thread, mode="fast", text="ping")
    dt = (time.time() - t0) * 1000
    ok = dt < 2000  # loose in CI env
    return EvalResult("latency_smoke", ok, f"ttft_sim_ms={dt:.1f}")

def run_all(app: AgentMemoryApp) -> List[EvalResult]:
    thread = "eval"
    results = [
        needle_test(app, thread),
        temporal_contradiction_test(app, thread),
        mode_stability_test(app, thread),
        latency_smoke_test(app, thread),
    ]
    return results
