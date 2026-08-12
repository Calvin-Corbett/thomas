"""CAP-146 L2: disfluency-aware structured intent extraction from voice transcripts.

Turns a raw (possibly disfluent) speech transcript into a fluent utterance and a
structured intent, over three cleanly separated stages behind an injectable
speech-to-text seam:

1. **ASR adapter** (:class:`ASRAdapter`) -- an injectable speech-to-text edge.
   The real default (:class:`CommandLineASR`) shells out to an external ASR
   binary (e.g. a ``whisper`` CLI) through an injected runner, so no audio
   decoding or network call lives in this module and no new pip dependency is
   introduced. The hermetic fake (:class:`FakeASR`) returns canned transcripts
   keyed by audio reference for tests -- it never touches audio or the network.

2. **Disfluency cleanup** (:func:`clean_disfluencies`) -- removes filler words
   (``um`` / ``uh`` / ``er`` ...), false starts, and immediate word/phrase
   repetitions, yielding a fluent utterance while preserving meaning. Every
   removed token is reported as evidence.

3. **Intent extraction** (:class:`IntentRegistry`) -- maps the cleaned utterance
   to a structured intent (name + slot values) over a small registered intent
   set using deterministic rule/pattern matching (no ML dependency). A
   filler-only or trigger-less utterance yields the explicit no-intent result
   (:data:`NO_INTENT`, confidence ``0.0``) rather than a hallucinated intent.

The whole core is deterministic and hermetic; :class:`VoiceIntentPipeline`
stitches the three stages together.

This module depends only on the standard library (tools layer rule: no imports
from agent/server/cli).
"""

from __future__ import annotations

import logging
import re
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Disfluency vocabulary
# ---------------------------------------------------------------------------

#: Standalone filler tokens removed wholesale during cleanup. Conservative on
#: purpose -- only tokens that are fillers in isolation (``like`` / ``you know``
#: are intentionally excluded because they routinely carry meaning).
FILLER_WORDS: frozenset[str] = frozenset({"um", "uh", "er", "erm", "uhm", "hmm", "mm", "mmhmm", "uhhuh", "ah", "eh"})

#: Longest repeated phrase (in tokens) that a false start may span.
_MAX_REPEAT_PHRASE = 4

_TOKEN_STRIP = ".,!?;:\"'"

#: Sentinel intent name returned when nothing matches with confidence.
NO_INTENT = "none"


# ---------------------------------------------------------------------------
# ASR adapter seam
# ---------------------------------------------------------------------------


class ASRError(RuntimeError):
    """Raised when the real ASR edge cannot produce a transcript."""


class ASRAdapter(ABC):
    """Injectable speech-to-text edge: audio reference in, transcript out."""

    @abstractmethod
    def transcribe(self, audio_ref: str) -> str:
        """Return the transcript for the audio at ``audio_ref``."""
        raise NotImplementedError


#: Runner seam for :class:`CommandLineASR` -- mirrors ``subprocess.run``.
CommandRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def _default_command_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- argv is caller-provided template, not shell
        list(argv),
        capture_output=True,
        text=True,
        check=True,
    )


class CommandLineASR(ASRAdapter):
    """Real default ASR edge: invoke an external transcription binary.

    The command template is an argv list containing the literal token
    ``{audio}``, which is replaced with the audio reference at call time (e.g.
    ``["whisper", "--model", "base", "--output", "txt", "{audio}"]``). The
    subprocess call is the live lane: it requires a real ASR binary on ``PATH``
    and is therefore not exercised by the hermetic test suite (which injects a
    fake ``runner`` or uses :class:`FakeASR`). No audio decoding happens here.
    """

    def __init__(
        self,
        command_template: Sequence[str],
        *,
        runner: CommandRunner | None = None,
    ) -> None:
        if not any("{audio}" in part for part in command_template):
            raise ValueError("command_template must contain a '{audio}' placeholder")
        self._template = tuple(command_template)
        self._runner = runner or _default_command_runner

    def transcribe(self, audio_ref: str) -> str:
        argv = [part.replace("{audio}", audio_ref) for part in self._template]
        try:
            completed = self._runner(argv)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            logger.warning("ASR command failed for %s: %s", audio_ref, exc)
            raise ASRError(f"ASR command failed for {audio_ref!r}: {exc}") from exc
        return (completed.stdout or "").strip()


class FakeASR(ASRAdapter):
    """Hermetic ASR fake: return canned transcripts, no audio and no network.

    Construct with either a single transcript (returned for any audio ref) or a
    mapping from audio ref to transcript. Unknown refs raise :class:`ASRError`
    so tests never silently pass on a typo.
    """

    def __init__(self, transcripts: str | Mapping[str, str]) -> None:
        if isinstance(transcripts, str):
            self._single: str | None = transcripts
            self._table: dict[str, str] = {}
        else:
            self._single = None
            self._table = dict(transcripts)

    def transcribe(self, audio_ref: str) -> str:
        if self._single is not None:
            return self._single
        try:
            return self._table[audio_ref]
        except KeyError as exc:
            raise ASRError(f"no canned transcript for {audio_ref!r}") from exc


# ---------------------------------------------------------------------------
# Stage 2: disfluency cleanup
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CleanupResult:
    """Outcome of disfluency cleanup.

    Attributes:
        utterance: The fluent, cleaned utterance.
        tokens: The cleaned utterance as a token list.
        removed_fillers: Filler tokens dropped, in order encountered.
        collapsed_repeats: Repeated phrases collapsed (the surviving copy of
            each immediate repetition), in order encountered.
    """

    utterance: str
    tokens: tuple[str, ...]
    removed_fillers: tuple[str, ...]
    collapsed_repeats: tuple[str, ...]


def _tokenize(text: str) -> list[str]:
    # Split on any run of whitespace or commas; commas mark false-start seams.
    parts = re.split(r"[\s,]+", text.strip())
    return [p for p in parts if p]


def _is_filler(token: str) -> bool:
    return token.strip(_TOKEN_STRIP).lower() in FILLER_WORDS


def _collapse_immediate_repeats(
    tokens: Sequence[str],
) -> tuple[list[str], list[str]]:
    """Collapse immediate repeated phrases (false starts), longest phrase first.

    Returns the deduplicated token list plus the surviving copy of every
    collapsed repetition (as space-joined phrases) for evidence.
    """
    result = list(tokens)
    collapsed: list[str] = []
    changed = True
    while changed:
        changed = False
        out: list[str] = []
        i = 0
        n = len(result)
        while i < n:
            matched = False
            max_span = min(_MAX_REPEAT_PHRASE, (n - i) // 2)
            for span in range(max_span, 0, -1):
                first = [t.strip(_TOKEN_STRIP).lower() for t in result[i : i + span]]
                second = [t.strip(_TOKEN_STRIP).lower() for t in result[i + span : i + 2 * span]]
                if first == second:
                    kept = result[i : i + span]
                    out.extend(kept)
                    collapsed.append(" ".join(kept))
                    i += 2 * span
                    matched = True
                    changed = True
                    break
            if not matched:
                out.append(result[i])
                i += 1
        result = out
    return result, collapsed


def clean_disfluencies(text: str) -> CleanupResult:
    """Remove fillers, false starts, and immediate repetitions from ``text``.

    Deterministic and side-effect free. Meaning is preserved: only fillers and
    the redundant copies of immediate repetitions are removed.
    """
    raw_tokens = _tokenize(text)

    kept: list[str] = []
    removed: list[str] = []
    for token in raw_tokens:
        if _is_filler(token):
            removed.append(token.strip(_TOKEN_STRIP).lower())
        else:
            kept.append(token.strip(_TOKEN_STRIP))

    deduped, collapsed = _collapse_immediate_repeats(kept)
    deduped = [t for t in deduped if t]

    return CleanupResult(
        utterance=" ".join(deduped),
        tokens=tuple(deduped),
        removed_fillers=tuple(removed),
        collapsed_repeats=tuple(collapsed),
    )


# ---------------------------------------------------------------------------
# Stage 3: intent extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotSpec:
    """A slot to fill from the utterance.

    Attributes:
        name: Slot name (e.g. ``"target"``).
        values: Canonical value -> accepted synonyms (lowercase). A token
            matching any synonym resolves the slot to the canonical value.
        required: When True, an unfilled slot lowers confidence.
    """

    name: str
    values: Mapping[str, tuple[str, ...]]
    required: bool = False


@dataclass(frozen=True)
class IntentSpec:
    """A registered intent.

    Attributes:
        name: Intent name (e.g. ``"deploy"``).
        triggers: Trigger keywords; at least one must appear in the utterance
            for the intent to be a candidate.
        slots: Slots to extract when the intent matches.
    """

    name: str
    triggers: tuple[str, ...]
    slots: tuple[SlotSpec, ...] = ()


@dataclass(frozen=True)
class IntentResult:
    """Structured intent extracted from a cleaned utterance.

    Attributes:
        intent: Intent name, or :data:`NO_INTENT` when nothing matched.
        slots: Resolved slot values (canonical).
        confidence: Deterministic score in ``[0.0, 1.0]``.
        matched_trigger: The trigger keyword that fired, or ``None``.
    """

    intent: str
    slots: dict[str, str]
    confidence: float
    matched_trigger: str | None = None


class IntentRegistry:
    """Deterministic rule-based intent matcher over a small registered set."""

    def __init__(self, intents: Iterable[IntentSpec] | None = None) -> None:
        self._intents: list[IntentSpec] = list(intents or ())

    def register(self, spec: IntentSpec) -> None:
        self._intents.append(spec)

    @property
    def intents(self) -> tuple[IntentSpec, ...]:
        return tuple(self._intents)

    def extract(self, tokens: Sequence[str]) -> IntentResult:
        """Map ``tokens`` (a cleaned utterance) to the best structured intent."""
        norm = [t.strip(_TOKEN_STRIP).lower() for t in tokens if t]
        token_set = set(norm)

        best: IntentResult | None = None
        for spec in self._intents:  # registry order is the deterministic tiebreak
            trigger = next((t for t in spec.triggers if t in token_set), None)
            if trigger is None:
                continue
            slots, filled, total = self._fill_slots(spec, norm)
            slot_score = (filled / total) if total else 1.0
            confidence = round(0.5 + 0.5 * slot_score, 3)
            if best is None or confidence > best.confidence:
                best = IntentResult(
                    intent=spec.name,
                    slots=slots,
                    confidence=confidence,
                    matched_trigger=trigger,
                )

        if best is None:
            return IntentResult(intent=NO_INTENT, slots={}, confidence=0.0)
        return best

    @staticmethod
    def _fill_slots(spec: IntentSpec, norm: Sequence[str]) -> tuple[dict[str, str], int, int]:
        slots: dict[str, str] = {}
        required_total = 0
        required_filled = 0
        for slot in spec.slots:
            if slot.required:
                required_total += 1
            resolved = None
            for canonical, synonyms in slot.values.items():
                if any(syn in norm for syn in synonyms):
                    resolved = canonical
                    break
            if resolved is not None:
                slots[slot.name] = resolved
                if slot.required:
                    required_filled += 1
        return slots, required_filled, required_total


def default_intent_registry() -> IntentRegistry:
    """A small, opinionated default intent set for operational voice commands."""
    env_values = {
        "staging": ("staging", "stage"),
        "production": ("production", "prod", "prd"),
        "development": ("development", "dev"),
    }
    return IntentRegistry(
        [
            IntentSpec(
                name="deploy",
                triggers=("deploy", "ship", "release"),
                slots=(SlotSpec(name="target", values=env_values),),
            ),
            IntentSpec(
                name="rollback",
                triggers=("rollback", "revert", "roll"),
                slots=(SlotSpec(name="target", values=env_values),),
            ),
            IntentSpec(
                name="restart",
                triggers=("restart", "reboot", "bounce"),
                slots=(SlotSpec(name="target", values=env_values),),
            ),
            IntentSpec(
                name="status",
                triggers=("status", "health", "check"),
                slots=(SlotSpec(name="target", values=env_values),),
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VoiceIntentResult:
    """Full pipeline outcome: transcript -> fluent utterance -> structured intent.

    Attributes:
        audio_ref: The audio reference that was transcribed.
        transcript: The raw (possibly disfluent) transcript from the ASR edge.
        utterance: The cleaned, fluent utterance.
        intent: Intent name (or :data:`NO_INTENT`).
        slots: Resolved slot values.
        confidence: Intent confidence in ``[0.0, 1.0]``.
        is_actionable: True when an intent matched at or above the pipeline's
            confidence threshold.
        removed_fillers: Filler tokens removed during cleanup (evidence).
        collapsed_repeats: Repeated phrases collapsed during cleanup (evidence).
    """

    audio_ref: str
    transcript: str
    utterance: str
    intent: str
    slots: dict[str, str]
    confidence: float
    is_actionable: bool
    removed_fillers: tuple[str, ...] = field(default_factory=tuple)
    collapsed_repeats: tuple[str, ...] = field(default_factory=tuple)


class VoiceIntentPipeline:
    """Compose the ASR edge, disfluency cleanup, and intent extraction."""

    def __init__(
        self,
        asr: ASRAdapter,
        *,
        registry: IntentRegistry | None = None,
        min_confidence: float = 0.5,
    ) -> None:
        self._asr = asr
        self._registry = registry or default_intent_registry()
        self._min_confidence = min_confidence

    def process(self, audio_ref: str) -> VoiceIntentResult:
        transcript = self._asr.transcribe(audio_ref)
        return self.process_transcript(transcript, audio_ref=audio_ref)

    def process_transcript(self, transcript: str, *, audio_ref: str = "") -> VoiceIntentResult:
        """Run cleanup + extraction on an already-obtained transcript."""
        cleanup = clean_disfluencies(transcript)
        intent = self._registry.extract(cleanup.tokens)
        is_actionable = intent.intent != NO_INTENT and intent.confidence >= self._min_confidence
        return VoiceIntentResult(
            audio_ref=audio_ref,
            transcript=transcript,
            utterance=cleanup.utterance,
            intent=intent.intent,
            slots=intent.slots,
            confidence=intent.confidence,
            is_actionable=is_actionable,
            removed_fillers=cleanup.removed_fillers,
            collapsed_repeats=cleanup.collapsed_repeats,
        )
