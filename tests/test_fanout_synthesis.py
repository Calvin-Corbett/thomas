"""Tests for six-way prompt fan-out with conflict-aware synthesis.

Acceptance line (CAP-029): "Activate and prove six-way fan-out with independent
evidence and conflict-aware synthesis."

Every worker here is a deterministic in-process fake -- no live model, no
network. Independence is proven by asserting each worker saw the same prompt
yet produced its own evidence record; conflict-awareness is proven by asserting
a split is surfaced (both sides + dissenters named) rather than silently
majority-picked.
"""

from __future__ import annotations

import dataclasses

import pytest

from thomas.agent.fanout_synthesis import (
    DEFAULT_FANOUT,
    ClaimGroup,
    ConflictReport,
    Evidence,
    FanoutSynthesizer,
    Outcome,
    SynthesisConfig,
    WorkerRequest,
    WorkerResult,
    default_normalizer,
    fan_out_and_synthesize,
)

# ---------------------------------------------------------------------------
# Deterministic fake workers
# ---------------------------------------------------------------------------


def make_scripted_worker(script):
    """A worker whose answer is looked up per worker-id from ``script``.

    ``script`` maps worker_id -> answer string. Each invocation records the
    prompt it saw and returns an evidence record unique to that worker.
    """

    seen: list[WorkerRequest] = []

    def worker(request: WorkerRequest):
        seen.append(request)
        answer = script[request.worker_id]
        return WorkerResult(
            worker_id="IGNORED-should-be-restamped",
            index=-999,
            prompt="IGNORED-should-be-restamped",
            answer=answer,
            evidence=Evidence(
                worker_id="IGNORED-should-be-restamped",
                summary=f"{request.worker_id} derived {answer!r}",
                sources=(f"src://{request.worker_id}",),
            ),
        )

    worker.seen = seen  # type: ignore[attr-defined]
    return worker


def unanimous_worker(request: WorkerRequest):
    """Every worker independently returns the same answer with its own evidence."""

    return {
        "answer": "42",
        "evidence": {
            "summary": f"{request.worker_id} computed 6 * 7",
            "sources": [f"calc://{request.index}"],
        },
    }


# ---------------------------------------------------------------------------
# Six-way fan-out with independent evidence
# ---------------------------------------------------------------------------


def test_default_fanout_is_six():
    synth = FanoutSynthesizer(unanimous_worker)
    assert synth.fanout == 6
    assert DEFAULT_FANOUT == 6
    assert synth.worker_ids == tuple(f"worker-{i}" for i in range(6))


def test_six_way_fanout_runs_all_workers_independently_with_own_evidence():
    worker = make_scripted_worker({f"worker-{i}": f"answer-{i}" for i in range(6)})
    synth = FanoutSynthesizer(worker)

    result = synth.run("what is the capital of France?")

    # 1. Exactly six workers ran, once each, for the ONE prompt.
    assert result.worker_count == 6
    assert len(worker.seen) == 6
    assert [r.index for r in result.worker_results] == [0, 1, 2, 3, 4, 5]

    # 2. Every worker received the SAME prompt (independence: same question).
    assert set(result.prompts_seen) == {"what is the capital of France?"}
    assert [req.prompt for req in worker.seen] == ["what is the capital of France?"] * 6

    # 3. Six DISTINCT evidence records, each stamped with its own worker id,
    #    for the single prompt -- no shared evidence object.
    evidence = result.evidence_records
    assert len(evidence) == 6
    assert len({e.worker_id for e in evidence}) == 6
    assert len({id(e) for e in evidence}) == 6  # distinct objects, no aliasing
    for i, ev in enumerate(evidence):
        assert ev.worker_id == f"worker-{i}"
        assert ev.sources == (f"src://worker-{i}",)

    # 4. Worker identity is authoritative: the synthesizer re-stamps the id the
    #    worker tried to fake, proving the fan-out controls independence.
    for i, wr in enumerate(result.worker_results):
        assert wr.worker_id == f"worker-{i}"
        assert wr.evidence.worker_id == f"worker-{i}"


def test_full_agreement_yields_consensus_synthesis():
    result = fan_out_and_synthesize("6*7?", unanimous_worker)

    assert result.outcome is Outcome.CONSENSUS
    assert result.is_consensus
    assert result.resolved
    assert result.answer == "42"
    assert result.conflict is None
    assert result.consensus_group is not None
    assert result.consensus_group.support == 6
    # Still six independent evidence records backing the consensus.
    assert len(result.evidence_records) == 6
    assert len({e.worker_id for e in result.evidence_records}) == 6
    assert result.dissenting_worker_ids() == ()
    assert "consensus of 6 workers" in result.describe()


# ---------------------------------------------------------------------------
# Conflict-aware synthesis: split is surfaced, never silently majority-picked
# ---------------------------------------------------------------------------


def test_four_two_split_is_surfaced_as_conflict_not_silently_majority_picked():
    # 4 workers say "yes", 2 say "no".
    script = {
        "worker-0": "yes",
        "worker-1": "yes",
        "worker-2": "yes",
        "worker-3": "yes",
        "worker-4": "no",
        "worker-5": "no",
    }
    result = fan_out_and_synthesize("ship it?", make_scripted_worker(script))

    # NOT silently resolved to the majority "yes".
    assert result.outcome is Outcome.CONFLICT
    assert result.is_conflict
    assert result.answer is None  # withheld, not the 4-vote plurality
    assert not result.resolved

    conflict = result.conflict
    assert isinstance(conflict, ConflictReport)
    assert conflict.resolved is False
    assert conflict.total_workers == 6

    # Both sides are represented with their supporting evidence.
    assert len(conflict.groups) == 2
    majority, minority = conflict.groups  # ranked by support desc
    assert (majority.answer, majority.support) == ("yes", 4)
    assert (minority.answer, minority.support) == ("no", 2)
    assert majority.worker_ids == ("worker-0", "worker-1", "worker-2", "worker-3")
    assert minority.worker_ids == ("worker-4", "worker-5")
    # Each side carries per-worker evidence.
    assert len(majority.evidence) == 4
    assert len(minority.evidence) == 2
    assert {e.worker_id for e in minority.evidence} == {"worker-4", "worker-5"}

    # The dissenters are named explicitly.
    assert result.dissenting_worker_ids() == ("worker-4", "worker-5")
    description = result.describe()
    assert "no consensus" in description
    assert "worker-4" in description and "worker-5" in description


def test_single_dissenter_still_flagged_under_default_unanimous_policy():
    script = {f"worker-{i}": "yes" for i in range(6)}
    script["worker-5"] = "no"
    result = fan_out_and_synthesize("agree?", make_scripted_worker(script))

    assert result.outcome is Outcome.CONFLICT
    assert result.answer is None
    assert result.dissenting_worker_ids() == ("worker-5",)


def test_supermajority_threshold_resolves_split_but_still_records_dissent():
    # 5 "yes", 1 "no"; threshold 0.66 lets the supermajority resolve it.
    script = {f"worker-{i}": "yes" for i in range(6)}
    script["worker-3"] = "no"
    result = fan_out_and_synthesize(
        "agree?",
        make_scripted_worker(script),
        config=SynthesisConfig(consensus_threshold=0.66),
    )

    assert result.outcome is Outcome.SUPERMAJORITY
    assert result.answer == "yes"  # resolved above an explicit threshold
    assert result.resolved
    # Dissent is NOT hidden: the conflict report is still attached.
    assert result.conflict is not None
    assert result.conflict.resolved is True
    assert result.dissenting_worker_ids() == ("worker-3",)
    assert "supermajority" in result.describe()


def test_threshold_not_met_falls_back_to_conflict():
    # 4 vs 2 = 0.667 top fraction; threshold 0.8 not met -> unresolved conflict.
    script = {
        "worker-0": "a",
        "worker-1": "a",
        "worker-2": "a",
        "worker-3": "a",
        "worker-4": "b",
        "worker-5": "b",
    }
    result = fan_out_and_synthesize(
        "?",
        make_scripted_worker(script),
        config=SynthesisConfig(consensus_threshold=0.8),
    )
    assert result.outcome is Outcome.CONFLICT
    assert result.answer is None


# ---------------------------------------------------------------------------
# Normalization, determinism, configurable N
# ---------------------------------------------------------------------------


def test_trivial_formatting_differences_count_as_agreement():
    script = {
        "worker-0": "Yes.",
        "worker-1": " yes. ",
        "worker-2": "YES.",
        "worker-3": "yes.",
        "worker-4": "Yes.",
        "worker-5": "yes.",
    }
    result = fan_out_and_synthesize("ok?", make_scripted_worker(script))
    assert result.outcome is Outcome.CONSENSUS
    # Representative answer is the first worker's raw form.
    assert result.answer == "Yes."


def test_default_normalizer_behavior():
    assert default_normalizer("  Hello   World ") == "hello world"
    assert default_normalizer("Yes.") == default_normalizer(" yes. ")


def test_synthesis_is_deterministic_for_fixed_worker_outputs():
    script = {
        "worker-0": "x",
        "worker-1": "y",
        "worker-2": "x",
        "worker-3": "z",
        "worker-4": "y",
        "worker-5": "x",
    }
    results = [fan_out_and_synthesize("q", make_scripted_worker(dict(script))) for _ in range(5)]
    baseline = results[0]
    for other in results[1:]:
        assert other.outcome == baseline.outcome
        assert other.answer == baseline.answer
        assert other.describe() == baseline.describe()
        assert [(g.answer, g.worker_ids) for g in other.groups] == [(g.answer, g.worker_ids) for g in baseline.groups]
    # Ranked by support desc, then first-seen index asc: x(3) then y(2) then z(1).
    assert [(g.answer, g.support) for g in baseline.groups] == [
        ("x", 3),
        ("y", 2),
        ("z", 1),
    ]


def test_fanout_is_configurable_prove_at_three_and_twelve():
    for n in (3, 12):
        worker = make_scripted_worker({f"worker-{i}": "same" for i in range(n)})
        synth = FanoutSynthesizer(worker, fanout=n)
        assert synth.fanout == n
        result = synth.run("p")
        assert result.worker_count == n
        assert len(result.evidence_records) == n
        assert len({e.worker_id for e in result.evidence_records}) == n
        assert result.outcome is Outcome.CONSENSUS
        assert result.answer == "same"


def test_custom_worker_ids_and_uniqueness_guard():
    worker = make_scripted_worker({"alpha": "1", "beta": "1", "gamma": "2"})
    synth = FanoutSynthesizer(worker, worker_ids=["alpha", "beta", "gamma"])
    assert synth.worker_ids == ("alpha", "beta", "gamma")
    result = synth.run("p")
    assert result.outcome is Outcome.CONFLICT
    assert result.dissenting_worker_ids() == ("gamma",)

    with pytest.raises(ValueError):
        FanoutSynthesizer(worker, worker_ids=["dup", "dup"])


# ---------------------------------------------------------------------------
# Worker return coercion + guards
# ---------------------------------------------------------------------------


def test_worker_may_return_mapping_with_string_evidence():
    def worker(request: WorkerRequest):
        return {"answer": "ok", "evidence": f"note from {request.worker_id}"}

    result = fan_out_and_synthesize("p", worker, fanout=6)
    assert result.outcome is Outcome.CONSENSUS
    assert result.evidence_records[0].summary == "note from worker-0"
    assert all(e.worker_id == f"worker-{i}" for i, e in enumerate(result.evidence_records))


def test_worker_returning_bad_type_raises():
    def worker(request: WorkerRequest):
        return 12345  # not a WorkerResult or mapping

    with pytest.raises(TypeError):
        fan_out_and_synthesize("p", worker, fanout=2)


def test_worker_mapping_without_answer_raises():
    def worker(request: WorkerRequest):
        return {"evidence": "nope"}

    with pytest.raises(ValueError):
        fan_out_and_synthesize("p", worker, fanout=2)


def test_invalid_threshold_rejected():
    with pytest.raises(ValueError):
        SynthesisConfig(consensus_threshold=0.0)
    with pytest.raises(ValueError):
        SynthesisConfig(consensus_threshold=1.5)


def test_empty_synthesis_rejected():
    synth = FanoutSynthesizer(unanimous_worker, fanout=1)
    with pytest.raises(ValueError):
        synth.synthesize("p", [])


def test_worker_result_evidence_restamped_even_when_evidence_omitted():
    def worker(request: WorkerRequest):
        return {"answer": "y"}  # no evidence key

    result = fan_out_and_synthesize("p", worker, fanout=3)
    assert all(isinstance(e, Evidence) for e in result.evidence_records)
    assert [e.worker_id for e in result.evidence_records] == [
        "worker-0",
        "worker-1",
        "worker-2",
    ]


def test_claimgroup_and_dataclasses_are_frozen():
    ev = Evidence(worker_id="w", summary="s")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.summary = "x"  # type: ignore[misc]
    group = ClaimGroup(normalized="a", answer="a", worker_ids=("w",), evidence=(ev,), first_index=0)
    assert group.support == 1
