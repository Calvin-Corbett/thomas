"""CAP-146 L2: disfluency cleanup + structured intent from voice transcripts.

Proves the exact acceptance line against a hermetic injected ASR fake:

- A disfluent transcript ("um, can you, uh, can you deploy the, the staging
  build") is cleaned to a fluent utterance AND mapped to intent=deploy with
  target=staging.
- A filler-only utterance yields the explicit no-intent / low-confidence result
  (not a hallucinated intent).
- Immediate word and phrase repetitions (false starts) are collapsed.
- The pipeline is deterministic: identical input yields identical output.

No real audio and no network: ASR is injected as a canned fake.
"""

from __future__ import annotations

import subprocess

import pytest

from thomas.tools.voice_intent import (
    NO_INTENT,
    ASRError,
    CommandLineASR,
    FakeASR,
    VoiceIntentPipeline,
    clean_disfluencies,
    default_intent_registry,
)

DISFLUENT_DEPLOY = "um, can you, uh, can you deploy the, the staging build"
FILLER_ONLY = "um, uh, er, um, hmm"


def _pipeline(transcript: str, ref: str = "clip-1") -> VoiceIntentPipeline:
    return VoiceIntentPipeline(FakeASR({ref: transcript}))


def test_disfluent_transcript_cleaned_and_mapped_to_deploy_staging() -> None:
    """The headline acceptance line: clean + structured intent from one clip."""
    pipeline = _pipeline(DISFLUENT_DEPLOY)

    result = pipeline.process("clip-1")

    # Cleaned to a fluent utterance (fillers gone, false start collapsed).
    assert result.utterance == "can you deploy the staging build"
    # Mapped to the structured intent with the extracted slot.
    assert result.intent == "deploy"
    assert result.slots == {"target": "staging"}
    assert result.is_actionable is True
    assert result.confidence == 1.0
    # Evidence of what was removed.
    assert "um" in result.removed_fillers
    assert "uh" in result.removed_fillers
    assert "can you" in result.collapsed_repeats
    assert "the" in result.collapsed_repeats


def test_filler_only_yields_no_intent_not_a_hallucination() -> None:
    """A filler-only utterance must NOT be forced into a real intent."""
    pipeline = _pipeline(FILLER_ONLY)

    result = pipeline.process("clip-1")

    assert result.utterance == ""
    assert result.intent == NO_INTENT
    assert result.slots == {}
    assert result.confidence == 0.0
    assert result.is_actionable is False


def test_immediate_word_and_phrase_repetitions_are_collapsed() -> None:
    cleanup = clean_disfluencies("deploy deploy the the the prod prod build")

    assert cleanup.utterance == "deploy the prod build"
    # Single-word ("the", "prod") and word ("deploy") repetitions all collapse.
    assert cleanup.collapsed_repeats.count("the") >= 1
    assert "deploy" in cleanup.collapsed_repeats
    assert "prod" in cleanup.collapsed_repeats


def test_multiword_false_start_phrase_is_collapsed() -> None:
    cleanup = clean_disfluencies("i want to i want to ship production now")

    assert cleanup.utterance == "i want to ship production now"
    assert "i want to" in cleanup.collapsed_repeats


def test_determinism_same_input_same_output() -> None:
    pipeline = _pipeline(DISFLUENT_DEPLOY)

    first = pipeline.process("clip-1")
    second = pipeline.process("clip-1")

    assert first == second


def test_rollback_and_status_intents_over_the_registered_set() -> None:
    reg = default_intent_registry()

    rollback = VoiceIntentPipeline(FakeASR("uh, rollback the production servers"), registry=reg).process_transcript(
        "uh, rollback the production servers"
    )
    assert rollback.intent == "rollback"
    assert rollback.slots == {"target": "production"}

    status = VoiceIntentPipeline(FakeASR("um check the dev status"), registry=reg).process_transcript(
        "um check the dev status"
    )
    assert status.intent == "status"
    assert status.slots == {"target": "development"}


def test_deploy_without_target_still_matches_with_lower_confidence() -> None:
    result = VoiceIntentPipeline(FakeASR("please deploy now")).process_transcript("please deploy now")

    assert result.intent == "deploy"
    assert result.slots == {}
    # No required slots, so a trigger-only match is still full confidence here.
    assert result.confidence == 1.0
    assert result.is_actionable is True


def test_fake_asr_unknown_ref_raises() -> None:
    with pytest.raises(ASRError):
        FakeASR({"clip-1": "hello"}).transcribe("missing")


def test_command_line_asr_uses_injected_runner_no_real_binary() -> None:
    """The real default edge shells out through an injected runner (hermetic)."""
    captured: dict[str, list[str]] = {}

    def fake_runner(argv):  # noqa: ANN001,ANN202 - test double
        captured["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="deploy staging\n", stderr="")

    asr = CommandLineASR(["whisper", "--txt", "{audio}"], runner=fake_runner)
    transcript = asr.transcribe("s3://bucket/clip.wav")

    assert transcript == "deploy staging"
    assert captured["argv"] == ["whisper", "--txt", "s3://bucket/clip.wav"]


def test_command_line_asr_requires_placeholder() -> None:
    with pytest.raises(ValueError, match="audio"):
        CommandLineASR(["whisper", "--txt"])


def test_command_line_asr_failure_wrapped_as_asr_error() -> None:
    def boom(argv):  # noqa: ANN001,ANN202 - test double
        raise FileNotFoundError("whisper not installed")

    asr = CommandLineASR(["whisper", "{audio}"], runner=boom)
    with pytest.raises(ASRError):
        asr.transcribe("clip.wav")
