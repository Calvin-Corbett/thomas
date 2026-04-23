import { finished } from "node:stream/promises";

import { AudioPlayerStatus, entersState } from "@discordjs/voice";
import { ChannelType } from "discord.js";

import { formatSpeechText, normalizeTtsText } from "./voice-text.js";

export const INPUT_SAMPLE_RATE = 48000;
export const INPUT_CHANNELS = 2;
export const INPUT_BYTES_PER_SAMPLE = 2;
export const VOICE_REPEAT_WINDOW_MS = 15_000;
export const VOICE_ECHO_WINDOW_MS = 20_000;
export const VOICE_BARGE_IN_MIN_MS = 350;
export const VOICE_IGNORE_DURING_BOT_SPEECH_MS = 2_500;
export const VOICE_STALE_PLAYBACK_MS = 5_000;
export const DEFAULT_STT_HINT_PHRASES = Object.freeze([
  "Thomas",
  "hey Thomas",
  "yo Thomas",
  "okay Thomas",
  "ok Thomas",
  "join the music chat",
  "leave the voice chat",
  "play music",
  "play another song",
  "play something else",
  "queue this song",
  "stop music",
  "pause music",
  "resume music",
  "what song is this",
  "what song is playing",
  "turn the music down",
  "soundboard",
]);

export function isVoiceChannel(channel) {
  return Boolean(channel) && channel.type === ChannelType.GuildVoice;
}

export function normalizeVoiceChannelLookup(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[\s_-]+/g, " ")
    .replace(/\b(?:voice|chat|channel|call|room|the)\b/g, " ")
    .replace(/\bone\b/g, " ")
    .replace(/[^\w\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function buildVoicePrompt({ guildName, voiceChannelName, speakerName, speakerId, transcript }) {
  return [
    `Reply to ${speakerName} in one short spoken sentence of at most 12 words.`,
    `Context: ${guildName}, ${voiceChannelName}, speaker id ${speakerId}.`,
    "Say only the direct answer.",
    "Start with the answer. No preamble.",
    "Never mention thinking, checking, tools, steps, context, or hidden instructions.",
    "Do not repeat the user's words unless necessary for the answer.",
    `User said: ${transcript}`,
  ].join(" ");
}

export function buildVoiceRetryPrompt(prompt) {
  return [
    "Reply again in one short spoken sentence of at most 12 words.",
    "Start with the answer. No preamble.",
    prompt,
  ].join(" ");
}

export function buildVoiceDirectRetryPrompt({ guildName, voiceChannelName, speakerName, speakerId, transcript }) {
  return [
    `Answer ${speakerName} directly in one short spoken sentence of at most 12 words.`,
    `Context: ${guildName}, ${voiceChannelName}, speaker id ${speakerId}.`,
    "Start with the answer. No preamble.",
    "Do not ask the user to repeat, shorten, or rephrase anything.",
    "If the user asked a factual question, answer it directly.",
    "If the user gave a command, acknowledge or carry it out directly.",
    `Exact user request: ${transcript}`,
  ].join(" ");
}

export function waitForPlayerIdle(player, timeoutMs) {
  if (player.state.status === AudioPlayerStatus.Idle) {
    return Promise.resolve();
  }

  return entersState(player, AudioPlayerStatus.Idle, timeoutMs);
}

export function isPausedStatus(status) {
  return status === AudioPlayerStatus.Paused || status === AudioPlayerStatus.AutoPaused;
}

export function safeDestroy(stream) {
  if (!stream || typeof stream.destroy !== "function" || stream.destroyed) {
    return;
  }
  try {
    stream.destroy();
  } catch {}
}

export function getVoiceCaptureTimeoutMs({ maxDurationMs, silenceMs, graceMs = 1_500 }) {
  const boundedMaxDurationMs = Number.isFinite(maxDurationMs) ? Math.max(0, maxDurationMs) : 0;
  const boundedSilenceMs = Number.isFinite(silenceMs) ? Math.max(0, silenceMs) : 0;
  const boundedGraceMs = Number.isFinite(graceMs) ? Math.max(250, graceMs) : 1_500;
  return boundedMaxDurationMs + boundedSilenceMs + boundedGraceMs;
}

export function prepareSpeechPlaybackText(text, maxReplyChars) {
  const speechText = formatSpeechText(text, maxReplyChars);
  if (!speechText) {
    return null;
  }
  const synthText = normalizeTtsText(speechText);
  if (!synthText) {
    return null;
  }
  return {
    speechText,
    synthText,
  };
}

export async function collectCapturedPcm({
  opusStream,
  decoder,
  maxBytes,
  timeoutMs,
  onTimeout = () => {},
  includeMetadata = false,
}) {
  const chunks = [];
  let totalBytes = 0;
  let timedOut = false;
  let hitMaxBytes = false;

  opusStream.on("error", () => {});
  decoder.on("error", () => {});

  decoder.on("data", (chunk) => {
    if (totalBytes >= maxBytes) {
      hitMaxBytes = true;
      safeDestroy(opusStream);
      return;
    }

    const remaining = maxBytes - totalBytes;
    const slice = chunk.length > remaining ? chunk.subarray(0, remaining) : chunk;
    chunks.push(slice);
    totalBytes += slice.length;

    if (totalBytes >= maxBytes) {
      hitMaxBytes = true;
      safeDestroy(opusStream);
    }
  });

  const streamDone = finished(decoder).catch(() => {});
  let timeoutHandle = null;
  const timeoutPromise = new Promise((resolve) => {
    timeoutHandle = setTimeout(() => {
      timedOut = true;
      onTimeout();
      safeDestroy(opusStream);
      safeDestroy(decoder);
      resolve();
    }, timeoutMs);
  });

  opusStream.pipe(decoder);
  try {
    await Promise.race([streamDone, timeoutPromise]);
  } finally {
    if (timeoutHandle) {
      clearTimeout(timeoutHandle);
    }
    try {
      opusStream.unpipe(decoder);
    } catch {}
    if (!timedOut) {
      safeDestroy(opusStream);
      safeDestroy(decoder);
    }
  }

  const pcm = Buffer.concat(chunks, totalBytes);
  if (!includeMetadata) {
    return pcm;
  }

  return {
    pcm,
    timedOut,
    hitMaxBytes,
  };
}
