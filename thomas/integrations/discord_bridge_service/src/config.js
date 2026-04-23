import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const DEFAULT_PROJECT_ROOT = path.resolve(fileURLToPath(new URL("../../../../", import.meta.url)));

function parseBoolean(value, fallback) {
  if (value == null || value === "") {
    return fallback;
  }

  const normalized = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }
  return fallback;
}

function parseCsv(value) {
  return new Set(
    String(value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  );
}

function parseInteger(value, fallback) {
  const parsed = Number.parseInt(String(value || ""), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseNumber(value, fallback) {
  const parsed = Number.parseFloat(String(value || ""));
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseList(value, fallback = []) {
  const items = String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return items.length > 0 ? items : [...fallback];
}

function requireValue(name) {
  const value = String(process.env[name] || "").trim();
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export function loadConfig() {
  const projectRoot = path.resolve(String(process.env.THOMAS_PROJECT_ROOT || DEFAULT_PROJECT_ROOT).trim() || DEFAULT_PROJECT_ROOT);
  const dataDir = path.resolve(
    String(process.env.DISCORD_DATA_DIR || path.join(projectRoot, "runtime", "discord_bridge")).trim(),
  );
  const baseUrl = String(process.env.THOMAS_BASE_URL || "http://127.0.0.1:8899").trim().replace(/\/+$/, "");
  const voiceTtsBackend = String(process.env.DISCORD_VOICE_TTS_BACKEND || "piper").trim() || "piper";
  const voiceSttBackend = String(process.env.DISCORD_VOICE_STT_BACKEND || "faster-whisper").trim() || "faster-whisper";

  return {
    discordToken: requireValue("DISCORD_BOT_TOKEN"),
    guildId: String(process.env.DISCORD_GUILD_ID || "").trim() || null,
    allowedGuildIds: parseCsv(process.env.DISCORD_ALLOWED_GUILD_IDS),
    autoChannelIds: parseCsv(process.env.DISCORD_AUTO_CHANNEL_IDS),
    ownerUserIds: parseCsv(process.env.DISCORD_OWNER_USER_IDS),
    ownerOnlyMode: parseBoolean(process.env.DISCORD_OWNER_ONLY_MODE, false),
    requireMention: parseBoolean(process.env.DISCORD_REQUIRE_MENTION, true),
    voiceAutoJoin: parseBoolean(process.env.DISCORD_VOICE_AUTO_JOIN, false),
    defaultVoiceChannelName: String(process.env.DISCORD_DEFAULT_VOICE_CHANNEL_NAME || "").trim() || null,
    voiceRequireWakeWord: parseBoolean(process.env.DISCORD_VOICE_REQUIRE_WAKE_WORD, true),
    voiceWakeWords: parseList(process.env.DISCORD_VOICE_WAKE_WORDS, [
      "thomas",
      "hey thomas",
      "yo thomas",
      "okay thomas",
      "ok thomas",
    ]),
    voiceSilenceMs: parseInteger(process.env.DISCORD_VOICE_SILENCE_MS, 700),
    voiceMinSpeechMs: parseInteger(process.env.DISCORD_VOICE_MIN_SPEECH_MS, 400),
    voiceMaxSpeechMs: parseInteger(process.env.DISCORD_VOICE_MAX_SPEECH_MS, 20000),
    voiceWakeCaptureMs: parseInteger(process.env.DISCORD_VOICE_WAKE_CAPTURE_MS, 6500),
    voiceNoWakeCooldownMs: parseInteger(process.env.DISCORD_VOICE_NO_WAKE_COOLDOWN_MS, 8000),
    voiceMaxReplyChars: parseInteger(process.env.DISCORD_VOICE_MAX_REPLY_CHARS, 320),
    voiceMediaVolume: Math.min(200, Math.max(0, parseInteger(process.env.DISCORD_VOICE_MEDIA_VOLUME, 100))),
    voiceAnnounceOnJoin: parseBoolean(process.env.DISCORD_VOICE_ANNOUNCE_ON_JOIN, true),
    voiceName: String(process.env.DISCORD_VOICE_NAME || "").trim() || null,
    voiceTtsBackend,
    voiceTtsPython: String(process.env.DISCORD_VOICE_TTS_PYTHON || "python").trim() || "python",
    voiceTtsModel: String(
      process.env.DISCORD_VOICE_TTS_MODEL
      || (voiceTtsBackend.toLowerCase() === "openai" ? "gpt-4o-mini-tts" : "en_US-ryan-high"),
    ).trim() || (voiceTtsBackend.toLowerCase() === "openai" ? "gpt-4o-mini-tts" : "en_US-ryan-high"),
    voiceTtsDataDir: String(process.env.DISCORD_VOICE_TTS_DATA_DIR || path.join(dataDir, "piper-voices")).trim(),
    voiceTtsUseCuda: parseBoolean(process.env.DISCORD_VOICE_TTS_USE_CUDA, false),
    voiceTtsSpeaker: process.env.DISCORD_VOICE_TTS_SPEAKER == null
      ? null
      : parseInteger(process.env.DISCORD_VOICE_TTS_SPEAKER, null),
    voiceTtsSentencePauseMs: parseInteger(process.env.DISCORD_VOICE_TTS_SENTENCE_PAUSE_MS, 140),
    voiceTtsLengthScale: process.env.DISCORD_VOICE_TTS_LENGTH_SCALE == null
      ? null
      : parseNumber(process.env.DISCORD_VOICE_TTS_LENGTH_SCALE, null),
    voiceTtsNoiseScale: process.env.DISCORD_VOICE_TTS_NOISE_SCALE == null
      ? null
      : parseNumber(process.env.DISCORD_VOICE_TTS_NOISE_SCALE, null),
    voiceTtsNoiseWScale: process.env.DISCORD_VOICE_TTS_NOISE_W_SCALE == null
      ? null
      : parseNumber(process.env.DISCORD_VOICE_TTS_NOISE_W_SCALE, null),
    voiceCloudVoice: String(process.env.DISCORD_VOICE_CLOUD_VOICE || "alloy").trim() || "alloy",
    voiceCloudResponseFormat: String(process.env.DISCORD_VOICE_CLOUD_RESPONSE_FORMAT || "wav").trim() || "wav",
    voiceOpenAiApiKey: String(
      process.env.DISCORD_VOICE_OPENAI_API_KEY
      || process.env.THOMAS_MODELS_OPENAI_API_KEY
      || process.env.OPENAI_API_KEY
      || "",
    ).trim() || null,
    voiceOpenAiBaseUrl: String(
      process.env.DISCORD_VOICE_OPENAI_BASE_URL
      || process.env.THOMAS_MODELS_OPENAI_BASE_URL
      || process.env.OPENAI_BASE_URL
      || "https://api.openai.com/v1",
    ).trim(),
    voiceSttBackend,
    voiceSttPython: String(process.env.DISCORD_VOICE_STT_PYTHON || "python").trim() || "python",
    voiceSttModel: String(
      process.env.DISCORD_VOICE_STT_MODEL
      || (voiceSttBackend.toLowerCase() === "openai" ? "gpt-4o-transcribe" : "distil-large-v3"),
    ).trim() || (voiceSttBackend.toLowerCase() === "openai" ? "gpt-4o-transcribe" : "distil-large-v3"),
    voiceSttDevice: String(process.env.DISCORD_VOICE_STT_DEVICE || "cpu").trim() || "cpu",
    voiceSttComputeType: String(process.env.DISCORD_VOICE_STT_COMPUTE_TYPE || "int8").trim() || "int8",
    voiceSttBeamSize: parseInteger(process.env.DISCORD_VOICE_STT_BEAM_SIZE, 5),
    voiceSttVadFilter: parseBoolean(process.env.DISCORD_VOICE_STT_VAD_FILTER, true),
    voiceSttVadMinSilenceMs: parseInteger(process.env.DISCORD_VOICE_STT_VAD_MIN_SILENCE_MS, 500),
    voiceSttLanguage: String(process.env.DISCORD_VOICE_STT_LANGUAGE || "en").trim() || null,
    voiceSttPrompt: String(process.env.DISCORD_VOICE_STT_PROMPT || "").trim() || null,
    voiceSttHintPhrases: parseList(process.env.DISCORD_VOICE_STT_HINT_PHRASES, []),
    mediaPython: String(
      process.env.DISCORD_MEDIA_PYTHON
        || process.env.DISCORD_VOICE_STT_PYTHON
        || process.env.DISCORD_VOICE_TTS_PYTHON
        || "python",
    ).trim() || "python",
    mediaSearchLimit: parseInteger(process.env.DISCORD_MEDIA_SEARCH_LIMIT, 3),
    thomasBaseUrl: baseUrl,
    thomasApiToken: String(process.env.THOMAS_SERVER_API_TOKEN || "").trim() || null,
    thomasTimeoutMs: parseInteger(process.env.THOMAS_REQUEST_TIMEOUT_MS, 180000),
    sessionPrefix: String(process.env.SESSION_PREFIX || "thomas-discord").trim(),
    maxReplyChars: parseInteger(process.env.DISCORD_MAX_REPLY_CHARS, 1900),
    dataDir,
  };
}
