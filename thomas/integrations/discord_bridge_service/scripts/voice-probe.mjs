import "dotenv/config";

import process from "node:process";
import { once } from "node:events";
import { parseArgs } from "node:util";

import { ChannelType, Client, Events, GatewayIntentBits } from "discord.js";

import { loadConfig } from "../src/config.js";
import { RuntimeSettingsStore } from "../src/runtime-settings-store.js";
import { SessionStore } from "../src/session-store.js";
import { ThomasClient } from "../src/thomas-client.js";
import { VoiceManager } from "../src/voice-manager.js";

function normalizeProbeText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function pickOwnerUserId(config) {
  const ownerIds = [...(config.ownerUserIds?.values?.() || [])];
  return ownerIds[0] || "voice-probe-user";
}

function buildRuntimeConfig(config, runtimeSettings) {
  return {
    ...config,
    requireMention: runtimeSettings.requireMention,
    voiceRequireWakeWord: runtimeSettings.voiceRequireWakeWord,
    voiceWakeWords: runtimeSettings.voiceWakeWords,
    voiceMediaVolume: runtimeSettings.voiceMediaVolume,
    voiceTtsModel: runtimeSettings.voiceProfile || config.voiceTtsModel,
  };
}

function buildRuntimeDefaults(config) {
  return {
    requireMention: config.requireMention,
    voiceRequireWakeWord: config.voiceRequireWakeWord,
    voiceWakeWords: config.voiceWakeWords,
    voiceMediaVolume: config.voiceMediaVolume,
    voiceProfile: config.voiceTtsModel,
    accessGrants: {},
  };
}

const { values } = parseArgs({
  options: {
    ask: { type: "string" },
    say: { type: "string" },
    wake: { type: "string" },
    channel: { type: "string" },
    "speaker-id": { type: "string" },
    "speaker-name": { type: "string" },
    "keep-audio": { type: "boolean", default: false },
    "probe-backend": { type: "string", default: "windows" },
    json: { type: "boolean", default: false },
  },
});

const config = loadConfig();
const settingsStore = new RuntimeSettingsStore({
  dataDir: config.dataDir,
  defaults: buildRuntimeDefaults(config),
});
await settingsStore.ensureLoaded();
const runtimeSettings = settingsStore.getState();
const runtimeConfig = buildRuntimeConfig(config, runtimeSettings);
const sessionStore = new SessionStore({
  dataDir: config.dataDir,
  sessionPrefix: config.sessionPrefix,
});
const thomas = new ThomasClient({
  baseUrl: runtimeConfig.thomasBaseUrl,
  apiToken: runtimeConfig.thomasApiToken,
  timeoutMs: runtimeConfig.thomasTimeoutMs,
});
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildVoiceStates,
    GatewayIntentBits.GuildMembers,
  ],
});

const ready = once(client, Events.ClientReady);
await client.login(runtimeConfig.discordToken);
await ready;
console.error("voice-probe-ready");

let voiceManager = null;
let joinedGuildId = "";

try {
  const guild = await client.guilds.fetch(runtimeConfig.guildId);
  const channels = await guild.channels.fetch();
  const targetChannel = String(values.channel || runtimeConfig.defaultVoiceChannelName || "").trim();
  const voiceChannel = [...channels.values()].find(
    (channel) =>
      channel
      && channel.type === ChannelType.GuildVoice
      && (channel.id === targetChannel || channel.name === targetChannel),
  );

  if (!voiceChannel) {
    throw new Error(`Voice channel not found: ${targetChannel || "(missing channel name)"}`);
  }
  console.error(`voice-probe-joining:${voiceChannel.name}`);

  voiceManager = new VoiceManager({
    client,
    config: runtimeConfig,
    thomas,
    sessionStore,
    settingsStore,
    enqueueByScope: async (_scopeKey, task) => task(),
  });
  const probeBackend = String(values["probe-backend"] || "windows").trim().toLowerCase();
  if (probeBackend === "windows") {
    voiceManager.speech = voiceManager.createSpeechService({
      ttsOverrides: {
        backend: "windows",
        useCuda: false,
      },
      sttOverrides: {
        backend: "windows",
      },
    });
  }

  const mode = values.wake ? "wake" : values.ask ? "ask" : "say";
  const speakerId = String(values["speaker-id"] || pickOwnerUserId(runtimeConfig)).trim();
  const speakerName = String(values["speaker-name"] || "Voice Probe").trim();
  const prompt = String(
    values.wake
      || values.ask
      || values.say
      || "Thomas voice check. Say that voice replies are working.",
  ).trim();

  await voiceManager.joinChannel(voiceChannel, { announce: false });
  joinedGuildId = guild.id;
  console.error(`voice-probe-joined:${voiceChannel.name}`);

  let replyText = prompt;
  if (mode === "ask") {
    console.error("voice-probe-asking");
    replyText = await voiceManager.askThomasInVoice({
      guildId: guild.id,
      speakerName,
      speakerId,
      text: prompt,
      speakOptions: { awaitPlayback: false },
    });
  } else if (mode === "wake") {
    console.error("voice-probe-wake");
    const member = await guild.members.fetch(speakerId).catch(() => null);
    const wakeResult = await voiceManager.processVoiceTranscript({
      guildId: guild.id,
      member,
      userId: speakerId,
      rawTranscript: prompt,
      speakOptions: { awaitPlayback: false },
    });
    if (!wakeResult?.handled) {
      throw new Error(`Wake probe did not produce a spoken reply: ${wakeResult?.action || "unknown"}`);
    }
    replyText = String(wakeResult.replyText || "").trim();
  } else {
    console.error("voice-probe-speaking");
    await voiceManager.speakText(guild.id, prompt, { awaitPlayback: false });
  }
  console.error("voice-probe-spoke");

  console.error("voice-probe-analyzing");
  const analysis = await voiceManager.analyzeSpokenText(replyText, {
    keepWav: Boolean(values["keep-audio"]),
  });
  console.error("voice-probe-analyzed");

  const result = {
    ok: true,
    mode,
    probe_backend: probeBackend,
    synth_backend: voiceManager.speech.describeSynthesizer(),
    stt_backend: voiceManager.speech.describeTranscriber(),
    guild_id: guild.id,
    voice_channel_id: voiceChannel.id,
    voice_channel_name: voiceChannel.name,
    speaker_id: speakerId,
    speaker_name: speakerName,
    prompt,
    raw_transcript: mode === "wake" ? prompt : "",
    reply_text: replyText,
    spoken_text: analysis?.speechText || "",
    synthesized_text: analysis?.synthText || "",
    transcribed_reply: analysis?.transcript || "",
    reply_matches_transcript:
      normalizeProbeText(analysis?.speechText) === normalizeProbeText(analysis?.transcript),
    wav_path: analysis?.wavPath || "",
  };

  if (values.json) {
    console.log(JSON.stringify(result));
  } else {
    console.log(JSON.stringify(result, null, 2));
  }
} finally {
  if (voiceManager && joinedGuildId) {
    await voiceManager.leaveGuild(joinedGuildId).catch(() => {});
  }
  voiceManager?.speech?.close?.();
  client.destroy();
}
