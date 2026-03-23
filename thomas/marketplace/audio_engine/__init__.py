"""
thomas.audio_engine: Digital Audio Processing Engine

A comprehensive audio processing library with synthesis, effects, filtering,
mixing, analysis, and spatial audio capabilities.
"""

__version__ = "0.1.0"

from thomas.marketplace.audio_engine._exceptions import (
    AudioEngineError,
    BufferOverflowError,
    EffectChainError,
    InvalidAudioFormatError,
)
from thomas.marketplace.audio_engine._types import (
    AudioBuffer,
    AudioBus,
    AudioClip,
    AudioFormat,
    AudioFrame,
    AudioTrack,
    BitDepth,
    Channel,
    Effect,
    EffectChain,
    EnvelopePoint,
    FilterType,
    MixerChannel,
    PanLaw,
    SampleRate,
    WaveformType,
)
from thomas.marketplace.audio_engine.analysis import (
    OnsetDetector,
    PitchDetector,
    SpectrogramAnalyzer,
    SpectrumAnalyzer,
)
from thomas.marketplace.audio_engine.buffer import (
    AudioBufferPool,
    ChannelConverter,
    RingBuffer,
    SampleConverter,
)
from thomas.marketplace.audio_engine.codecs import (
    ADPCMCodec,
    CompandingCodec,
    RawPCMCodec,
    WAVCodec,
)
from thomas.marketplace.audio_engine.effects import (
    Chorus,
    Compressor,
    Delay,
    Distortion,
    Flanger,
    Limiter,
    Reverb,
    Tremolo,
)
from thomas.marketplace.audio_engine.filters import (
    BiquadFilter,
    CrossoverFilter,
    FilterCascade,
    ParametricEQ,
)
from thomas.marketplace.audio_engine.mixer import (
    Mixer,
    VUMeter,
)
from thomas.marketplace.audio_engine.sequencer import (
    Note,
    PatternSequencer,
    TimelineEvent,
    Transport,
)
from thomas.marketplace.audio_engine.spatial import (
    BiauralRenderer,
    SpatialSource,
    StereoPane,
)
from thomas.marketplace.audio_engine.synthesis import (
    LFO,
    ADSREnvelope,
    NoiseGenerator,
    Oscillator,
    Wavetable,
)

__all__ = [
    "AudioFormat",
    "SampleRate",
    "BitDepth",
    "Channel",
    "AudioBuffer",
    "AudioFrame",
    "AudioClip",
    "AudioTrack",
    "AudioBus",
    "Effect",
    "EffectChain",
    "MixerChannel",
    "EnvelopePoint",
    "WaveformType",
    "FilterType",
    "PanLaw",
    "AudioEngineError",
    "InvalidAudioFormatError",
    "BufferOverflowError",
    "EffectChainError",
    "RingBuffer",
    "AudioBufferPool",
    "SampleConverter",
    "ChannelConverter",
    "Oscillator",
    "Wavetable",
    "NoiseGenerator",
    "ADSREnvelope",
    "LFO",
    "Delay",
    "Reverb",
    "Chorus",
    "Flanger",
    "Distortion",
    "Compressor",
    "Limiter",
    "Tremolo",
    "BiquadFilter",
    "FilterCascade",
    "ParametricEQ",
    "CrossoverFilter",
    "Mixer",
    "VUMeter",
    "SpectrumAnalyzer",
    "SpectrogramAnalyzer",
    "PitchDetector",
    "OnsetDetector",
    "StereoPane",
    "BiauralRenderer",
    "SpatialSource",
    "WAVCodec",
    "RawPCMCodec",
    "CompandingCodec",
    "ADPCMCodec",
    "Note",
    "TimelineEvent",
    "PatternSequencer",
    "Transport",
]
