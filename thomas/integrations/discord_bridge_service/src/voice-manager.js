import { MediaService } from "./media-service.js";
import { SpeechService } from "./speech-service.js";
import { discoverPiperVoiceProfiles } from "./voice-profiles.js";
import {
  DEFAULT_STT_HINT_PHRASES,
  collectCapturedPcm,
  getVoiceCaptureTimeoutMs,
  prepareSpeechPlaybackText,
} from "./voice-manager-shared.js";
import { voicePlaybackMethods } from "./voice-manager-playback.js";
import { voiceSessionMethods } from "./voice-manager-session.js";
import { voiceSpeechMethods } from "./voice-manager-speech.js";

export {
  collectCapturedPcm,
  getVoiceCaptureTimeoutMs,
  prepareSpeechPlaybackText,
} from "./voice-manager-shared.js";

function normalizeHintPhrase(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function collectHintPhraseVariants(value) {
  const source = normalizeHintPhrase(value);
  if (!source) {
    return [];
  }

  const variants = new Set([source]);
  const stripped = normalizeHintPhrase(
    source
      .replace(/\([^)]*\)/g, " ")
      .replace(/\[[^\]]*\]/g, " ")
      .replace(/[|]/g, " "),
  );
  if (stripped) {
    variants.add(stripped);
  }

  const pending = [source, stripped].filter(Boolean);
  const visited = new Set();
  while (pending.length > 0) {
    const candidate = normalizeHintPhrase(pending.shift());
    if (!candidate || visited.has(candidate)) {
      continue;
    }
    visited.add(candidate);
    variants.add(candidate);

    for (const splitter of [/\s+-\s+/g, /:\s+/g, /\s+by\s+/gi]) {
      const parts = candidate.split(splitter)
        .map((part) => normalizeHintPhrase(part))
        .filter((part) => part.length >= 3);
      for (const part of parts) {
        variants.add(part);
        if (!visited.has(part)) {
          pending.push(part);
        }
      }
    }

    const tokens = candidate.split(" ").filter(Boolean);
    if (tokens.length >= 2) {
      variants.add(tokens.slice(0, Math.min(tokens.length, 4)).join(" "));
    }
  }

  return [...variants]
    .map((item) => normalizeHintPhrase(item))
    .filter((item) => item.length >= 3 && item.length <= 80);
}

export class VoiceManager {
  constructor({ client, config, thomas, sessionStore, settingsStore, enqueueByScope, isOwnerUser, canUserUseCapability }) {
    this.client = client;
    this.config = config;
    this.thomas = thomas;
    this.sessionStore = sessionStore;
    this.settingsStore = settingsStore;
    this.enqueueByScope = enqueueByScope;
    this.isOwnerUser = isOwnerUser || (() => true);
    this.canUserUseCapability = canUserUseCapability || (() => true);
    this.voiceProfiles = discoverPiperVoiceProfiles(config.voiceTtsDataDir, config.voiceTtsModel);
    this.ttsRuntime = {
      backend: config.voiceTtsBackend,
      pythonBin: config.voiceTtsPython,
      model: config.voiceTtsModel,
      dataDir: config.voiceTtsDataDir,
      useCuda: config.voiceTtsUseCuda,
      speaker: config.voiceTtsSpeaker,
      sentencePauseMs: config.voiceTtsSentencePauseMs,
      lengthScale: config.voiceTtsLengthScale,
      noiseScale: config.voiceTtsNoiseScale,
      noiseWScale: config.voiceTtsNoiseWScale,
      openAiApiKey: config.voiceOpenAiApiKey,
      openAiBaseUrl: config.voiceOpenAiBaseUrl,
      openAiVoice: config.voiceCloudVoice,
      openAiResponseFormat: config.voiceCloudResponseFormat,
    };
    this.sttRuntime = {
      backend: config.voiceSttBackend,
      pythonBin: config.voiceSttPython,
      model: config.voiceSttModel,
      device: config.voiceSttDevice,
      computeType: config.voiceSttComputeType,
      beamSize: config.voiceSttBeamSize,
      vadFilter: config.voiceSttVadFilter,
      vadMinSilenceMs: config.voiceSttVadMinSilenceMs,
      language: config.voiceSttLanguage,
    };
    this.sessions = new Map();
    this.assetsReadyPromise = null;
    this.speech = this.createSpeechService();
    this.media = new MediaService({
      pythonBin: config.mediaPython,
    });
  }

  createSpeechService({ ttsOverrides = {}, sttOverrides = {} } = {}) {
    const tts = { ...this.ttsRuntime, ...ttsOverrides };
    const stt = { ...this.sttRuntime, ...sttOverrides };
    return new SpeechService({
      voiceName: this.config.voiceName,
      ttsBackend: tts.backend,
      ttsPythonBin: tts.pythonBin,
      ttsModel: tts.model,
      ttsDataDir: tts.dataDir,
      ttsUseCuda: tts.useCuda,
      ttsSpeaker: tts.speaker,
      ttsSentencePauseMs: tts.sentencePauseMs,
      ttsLengthScale: tts.lengthScale,
      ttsNoiseScale: tts.noiseScale,
      ttsNoiseWScale: tts.noiseWScale,
      openAiApiKey: tts.openAiApiKey,
      openAiBaseUrl: tts.openAiBaseUrl,
      openAiVoice: tts.openAiVoice,
      openAiResponseFormat: tts.openAiResponseFormat,
      sttBackend: stt.backend,
      sttPythonBin: stt.pythonBin,
      sttModel: stt.model,
      sttDevice: stt.device,
      sttComputeType: stt.computeType,
      sttBeamSize: stt.beamSize,
      sttVadFilter: stt.vadFilter,
      sttVadMinSilenceMs: stt.vadMinSilenceMs,
      sttLanguage: stt.language,
    });
  }

  getVoiceTranscriptionOptions(state = null) {
    const wakeWords = this.getVoiceWakeWords();
    const extraHints = Array.isArray(this.config.voiceSttHintPhrases)
      ? this.config.voiceSttHintPhrases
      : [];
    const contextualHints = new Set();
    const addHint = (value) => {
      for (const variant of collectHintPhraseVariants(value)) {
        contextualHints.add(variant);
      }
    };

    if (state) {
      addHint(state.lastRequestedQuery);
      for (const track of [
        state.currentTrack,
        state.lastTrack,
        ...(Array.isArray(state.queue) ? state.queue.slice(0, 3).map((entry) => entry?.track) : []),
      ]) {
        if (!track) {
          continue;
        }
        addHint(track.title);
        addHint(track.channel);
        addHint(track.uploader);
      }
    }

    const promptParts = [
      "Transcribe Discord voice chat for Thomas.",
      String(this.config.voiceSttPrompt || "").trim(),
      this.isVoiceWakeWordRequired() && wakeWords.length > 0
        ? `Wake phrases: ${wakeWords.join(", ")}.`
        : "",
      "Prefer exact song titles, artist names, and Discord command words from the hotwords list.",
      "Common commands: play, queue, pause, resume, stop, skip, volume, and what song is this.",
    ].filter(Boolean);
    return {
      hotwords: [
        ...wakeWords,
        ...extraHints,
        ...contextualHints,
        ...DEFAULT_STT_HINT_PHRASES,
      ],
      initialPrompt: promptParts.join(" "),
    };
  }
}

Object.assign(
  VoiceManager.prototype,
  voiceSessionMethods,
  voicePlaybackMethods,
  voiceSpeechMethods,
);
