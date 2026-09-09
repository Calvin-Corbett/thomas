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

  getVoiceTranscriptionOptions() {
    const wakeWords = this.getVoiceWakeWords();
    const extraHints = Array.isArray(this.config.voiceSttHintPhrases)
      ? this.config.voiceSttHintPhrases
      : [];
    const promptParts = [
      String(this.config.voiceSttPrompt || "").trim(),
      `The assistant name is Thomas. Common wake phrases include ${wakeWords.join(", ")}.`,
      "Common Discord voice commands include join the music chat, play music, stop music, pause music, and turn the music down.",
    ].filter(Boolean);
    return {
      hotwords: [
        ...wakeWords,
        ...extraHints,
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
