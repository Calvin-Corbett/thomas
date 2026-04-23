import test from "node:test";
import assert from "node:assert/strict";
import { PassThrough } from "node:stream";

import {
  collectCapturedPcm,
  getVoiceCaptureTimeoutMs,
  prepareSpeechPlaybackText,
  VoiceManager,
} from "../src/voice-manager.js";

test("getVoiceCaptureTimeoutMs adds silence and grace windows", () => {
  assert.equal(
    getVoiceCaptureTimeoutMs({
      maxDurationMs: 5_000,
      silenceMs: 900,
      graceMs: 600,
    }),
    6_500,
  );
});

test("prepareSpeechPlaybackText rejects blank inputs", () => {
  assert.equal(prepareSpeechPlaybackText("   ", 120), null);
});

test("getVoiceTranscriptionOptions includes wake words, extra hints, and music context", () => {
  const options = VoiceManager.prototype.getVoiceTranscriptionOptions.call({
    config: {
      voiceSttPrompt: "Prefer Discord music-control phrasing.",
      voiceSttHintPhrases: ["soundboard", "join the music chat"],
    },
    getVoiceWakeWords: () => ["thomas", "hey thomas"],
    isVoiceWakeWordRequired: () => true,
  });

  assert.match(options.initialPrompt, /Transcribe Discord voice chat for Thomas\./);
  assert.match(options.initialPrompt, /Prefer Discord music-control phrasing\./);
  assert.match(options.initialPrompt, /Wake phrases: thomas, hey thomas\./);
  assert.match(options.initialPrompt, /Prefer exact song titles, artist names, and Discord command words/);
  assert.ok(options.hotwords.includes("thomas"));
  assert.ok(options.hotwords.includes("soundboard"));
  assert.ok(options.hotwords.includes("join the music chat"));
});

test("getVoiceTranscriptionOptions biases toward current media names", () => {
  const options = VoiceManager.prototype.getVoiceTranscriptionOptions.call({
    config: {
      voiceSttPrompt: "",
      voiceSttHintPhrases: [],
    },
    getVoiceWakeWords: () => ["thomas"],
    isVoiceWakeWordRequired: () => false,
  }, {
    currentTrack: {
      title: "Lorna Shore - Pain Remains I: Dancing Like Flames",
      channel: "Century Media Records",
      uploader: "Century Media Records",
    },
    lastTrack: null,
    lastRequestedQuery: "pain remains by lorna shore",
    queue: [],
  });

  assert.ok(options.hotwords.includes("pain remains by lorna shore"));
  assert.ok(options.hotwords.includes("Lorna Shore - Pain Remains I: Dancing Like Flames"));
  assert.ok(options.hotwords.includes("Pain Remains I"));
  assert.ok(options.hotwords.includes("Century Media Records"));
});

test("collectCapturedPcm caps capture length and returns buffered audio", async () => {
  const opusStream = new PassThrough();
  const decoder = new PassThrough();

  const capturePromise = collectCapturedPcm({
    opusStream,
    decoder,
    maxBytes: 4,
    timeoutMs: 500,
  });

  opusStream.write(Buffer.from([1, 2, 3, 4, 5, 6]));
  const pcm = await capturePromise;

  assert.deepEqual([...pcm], [1, 2, 3, 4]);
  assert.equal(opusStream.destroyed, true);
  assert.equal(decoder.destroyed, true);
});

test("collectCapturedPcm times out and preserves partial capture", async () => {
  const opusStream = new PassThrough();
  const decoder = new PassThrough();
  let timedOut = false;

  const capturePromise = collectCapturedPcm({
    opusStream,
    decoder,
    maxBytes: 64,
    timeoutMs: 40,
    onTimeout: () => {
      timedOut = true;
    },
  });

  opusStream.write(Buffer.from([9, 8, 7]));
  const pcm = await capturePromise;

  assert.equal(timedOut, true);
  assert.deepEqual([...pcm], [9, 8, 7]);
  assert.equal(opusStream.destroyed, true);
  assert.equal(decoder.destroyed, true);
});

test("collectCapturedPcm can return timeout metadata for incomplete captures", async () => {
  const opusStream = new PassThrough();
  const decoder = new PassThrough();

  const capturePromise = collectCapturedPcm({
    opusStream,
    decoder,
    maxBytes: 64,
    timeoutMs: 40,
    includeMetadata: true,
  });

  opusStream.write(Buffer.from([5, 4, 3]));
  const capture = await capturePromise;

  assert.equal(capture.timedOut, true);
  assert.equal(capture.hitMaxBytes, false);
  assert.deepEqual([...capture.pcm], [5, 4, 3]);
});

test("handleSpeakingStart ignores incomplete long captures instead of replying over the user", async () => {
  const state = {
    destroyed: false,
    guildId: "guild-1",
    voiceChannelName: "General",
    player: { state: { status: "idle" } },
    playbackKind: null,
    lastSpokenAt: 0,
    listeningUsers: new Set(),
    ignoredUntilByUser: new Map(),
    lastTranscriptByUser: new Map(),
    guild: {
      members: {
        fetch: async () => ({
          id: "user-1",
          displayName: "Owner",
          user: { bot: false },
        }),
      },
    },
  };
  let transcribed = false;
  let processed = false;
  const manager = {
    client: { user: { id: "bot-1" } },
    config: {
      voiceNoWakeCooldownMs: 1_500,
      voiceMaxSpeechMs: 20_000,
      voiceWakeCaptureMs: 6_500,
      voiceMinSpeechMs: 400,
    },
    canUserTalk: () => true,
    canUserUseMedia: () => true,
    stopPlayer: () => {},
    isVoiceWakeWordRequired: () => false,
    captureUserSpeech: async () => ({
      pcm: Buffer.from([1, 2, 3, 4]),
      timedOut: true,
      hitMaxBytes: false,
    }),
    speech: {
      transcribeWav: async () => {
        transcribed = true;
        return "hello there";
      },
    },
    getVoiceTranscriptionOptions: () => ({}),
    processVoiceTranscript: async () => {
      processed = true;
    },
  };

  await VoiceManager.prototype.handleSpeakingStart.call(manager, state, "user-1");

  assert.equal(transcribed, false);
  assert.equal(processed, false);
  assert.equal(state.listeningUsers.size, 0);
});

test("handleSpeakingStart interrupts active speech before listening to the user", async () => {
  const state = {
    destroyed: false,
    guildId: "guild-1",
    voiceChannelName: "General",
    player: { state: { status: "playing" } },
    playbackKind: "speech",
    lastSpokenAt: Date.now() - 1_000,
    lastSpokenText: "Old Thomas reply",
    listeningUsers: new Set(),
    ignoredUntilByUser: new Map(),
    lastTranscriptByUser: new Map(),
    guild: {
      members: {
        fetch: async () => ({
          id: "user-1",
          displayName: "Owner",
          user: { bot: false },
        }),
      },
    },
  };
  let interrupted = 0;
  let processed = false;
  const manager = {
    client: { user: { id: "bot-1" } },
    config: {
      voiceNoWakeCooldownMs: 1_500,
      voiceMaxSpeechMs: 20_000,
      voiceWakeCaptureMs: 6_500,
      voiceMinSpeechMs: 100,
    },
    canUserTalk: () => true,
    canUserUseMedia: () => true,
    stopPlayer: () => {
      interrupted += 1;
      state.player.state.status = "idle";
      state.playbackKind = null;
    },
    isVoiceWakeWordRequired: () => false,
    captureUserSpeech: async () => ({
      pcm: Buffer.alloc(48_000),
      timedOut: false,
      hitMaxBytes: false,
    }),
    speech: {
      transcribeWav: async () => "hello there",
    },
    getVoiceTranscriptionOptions: () => ({}),
    processVoiceTranscript: async () => {
      processed = true;
    },
  };

  await VoiceManager.prototype.handleSpeakingStart.call(manager, state, "user-1");

  assert.equal(interrupted, 1);
  assert.equal(state.lastSpokenText, "");
  assert.equal(state.lastSpokenAt, 0);
  assert.equal(processed, true);
});
