"""Shared instrument for the Thomas chat-pipeline stress harness.

Calvin-directed, 2026-06-17. READ-ONLY AUDIT TOOL — it imports and drives the
REAL pipeline functions (no fork of Thomas), with deterministic stubs so there
is no network, no LLM cost, and no writes outside an isolated temp dir.

Each sweep records `Probe` rows (expected vs. actual + pass/fail + the rubric
dimension it grades + a severity) and dumps them to JSONL. `run_all.py`
aggregates the rows into a frontier-rubric scorecard.

The point is reproducibility: a defect is not an opinion here, it is a row you
can re-run in <2s that makes Thomas misbehave on demand.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# tests/stress/_harness.py -> repo root is parents[2]. Put it on sys.path so the
# sweeps can `import thomas.*` whether run as scripts or modules.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ARTIFACT_DIR = _REPO_ROOT / "plans" / "thomas" / "chat_stress_2026-06-17"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Deterministic fakes (mirrors tests/test_orchestrator_brain_completion_report.py)
# ---------------------------------------------------------------------------
class FakeDispatcher:
    """Captures every event the brain emits during a turn."""

    def __init__(self) -> None:
        self.text_parts: list[str] = []
        self.done_payloads: list[dict] = []
        self.events: list[dict] = []

    async def emit_text(self, text: str) -> None:
        self.text_parts.append(str(text))

    async def emit_done(self, **payload) -> None:
        self.done_payloads.append(dict(payload))

    async def emit(self, event) -> None:
        self.events.append(event if isinstance(event, dict) else {"event": str(event)})

    async def emit_memory_refresh(self, **kwargs) -> None:
        return None

    async def emit_delegation(self, **kwargs) -> None:
        self.events.append({"kind": "delegation", **kwargs})

    async def emit_agent_activity(self, **kwargs) -> None:
        self.events.append({"kind": "agent_activity", **kwargs})

    @property
    def text(self) -> str:
        return "".join(self.text_parts)


class FakeMemoryCtx:
    def __init__(self) -> None:
        self.working = ""
        self.episodic = ""
        self.semantic = ""
        self.total_tokens = 0

    def to_system_injection(self) -> str:
        return self.working


class FakeMemoryCoordinator:
    def __init__(self, *args, **kwargs) -> None:
        _ = (args, kwargs)

    async def refresh(self, **kwargs):
        _ = kwargs
        return FakeMemoryCtx()

    async def capture_episode(self, **kwargs):
        _ = kwargs
        return None


# ---------------------------------------------------------------------------
# Probe / Recorder
# ---------------------------------------------------------------------------
SEVERITIES = ("low", "med", "high", "critical")


@dataclass
class Probe:
    sweep: str
    case: str
    dimension: str  # rubric dimension id this grades
    expected: str
    actual: str
    passed: bool
    severity: str = "med"
    evidence: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            self.severity = "med"


@dataclass
class Recorder:
    sweep: str
    rows: list[Probe] = field(default_factory=list)

    def add(
        self,
        *,
        case: str,
        dimension: str,
        expected: str,
        actual: str,
        passed: bool,
        severity: str = "med",
        evidence: str = "",
    ) -> Probe:
        p = Probe(
            sweep=self.sweep,
            case=case,
            dimension=dimension,
            expected=str(expected),
            actual=str(actual),
            passed=bool(passed),
            severity=severity,
            evidence=str(evidence),
        )
        self.rows.append(p)
        return p

    # ---- output -------------------------------------------------------
    def dump(self) -> Path:
        path = ARTIFACT_DIR / f"results_{self.sweep}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for row in self.rows:
                fh.write(json.dumps(asdict(row)) + "\n")
        return path

    def console(self) -> None:
        total = len(self.rows)
        passed = sum(1 for r in self.rows if r.passed)
        failed = total - passed
        print(f"\n{'=' * 72}")
        print(f"SWEEP: {self.sweep}   {passed}/{total} passed   {failed} FAILED")
        print("=" * 72)
        for r in self.rows:
            mark = "PASS" if r.passed else f"FAIL[{r.severity}]"
            print(f"  [{mark:>10}] {r.case}")
            if not r.passed:
                print(f"               expected: {r.expected}")
                print(f"               actual:   {r.actual}")
                if r.evidence:
                    print(f"               evidence: {r.evidence}")
        path = self.dump()
        print(f"  -> {path.relative_to(_REPO_ROOT)}")
