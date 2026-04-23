import test from "node:test";
import assert from "node:assert/strict";

import { VoiceManager } from "../src/voice-manager.js";

test("applyRuntimeSettings updates live session volume and clears wake cooldowns", async () => {
  const volumeCalls = [];
  const state = {
    volumePercent: 100,
    currentAudioResource: {
      volume: {
        setVolume: (value) => {
          volumeCalls.push(value);
        },
      },
    },
    ignoredUntilByUser: new Map([["owner-1", Date.now() + 4000]]),
  };
  const manager = {
    sessions: new Map([["guild-1", state]]),
    config: {
      voiceMediaVolume: 100,
      voiceRequireWakeWord: true,
      voiceWakeWords: ["thomas"],
      requireMention: true,
    },
    ttsRuntime: {
      backend: "piper",
      model: "en_US-ryan-high",
    },
  };

  await VoiceManager.prototype.applyRuntimeSettings.call(
    manager,
    {
      voiceMediaVolume: 65,
      voiceRequireWakeWord: false,
      voiceWakeWords: ["thomas", "hey thomas"],
      requireMention: false,
      voiceProfile: "en_US-ryan-high",
    },
    {
      voiceMediaVolume: 100,
      voiceRequireWakeWord: true,
      voiceWakeWords: ["thomas"],
      requireMention: true,
      voiceProfile: "en_US-ryan-high",
    },
  );

  assert.equal(state.volumePercent, 65);
  assert.deepEqual(volumeCalls, [0.65]);
  assert.equal(state.ignoredUntilByUser.size, 0);
  assert.equal(manager.config.voiceRequireWakeWord, false);
  assert.equal(manager.config.requireMention, false);
});

test("handleNativeVoiceCommand adjusts relative volume without Thomas fallback", async () => {
  const state = {
    guildId: "guild-1",
    voiceChannelName: "General",
  };
  const linkedTexts = [];
  const manager = {
    changeVolumeByDelta: async (_guildId, deltaPercent) => {
      assert.equal(deltaPercent, 10);
      return { volumePercent: 110 };
    },
    sendLinkedText: async (_state, text) => {
      linkedTexts.push(text);
    },
  };

  const result = await VoiceManager.prototype.handleNativeVoiceCommand.call(
    manager,
    state,
    { displayName: "Owner" },
    { type: "volume_relative", deltaPercent: 10 },
  );

  assert.equal(result, "Volume 110 percent.");
  assert.deepEqual(linkedTexts, ["Voice volume set to 110 percent."]);
});

test("handleNativeVoiceCommand restarts the last track when resume lost the paused stream", async () => {
  const state = {
    guildId: "guild-1",
    voiceChannelName: "General",
    textChannelId: "text-1",
  };
  const linkedTexts = [];
  const manager = {
    resumeOrRestartPlayback: async (_guildId, payload) => {
      assert.equal(payload.requestedBy, "Owner");
      assert.equal(payload.textChannelId, "text-1");
      return {
        resumed: true,
        restarted: true,
        alreadyPlaying: false,
        track: { title: "Pain Remains I: Dancing Like Flames" },
      };
    },
    sendLinkedText: async (_state, text) => {
      linkedTexts.push(text);
    },
    summarizeTrackForSpeech: VoiceManager.prototype.summarizeTrackForSpeech,
  };

  const result = await VoiceManager.prototype.handleNativeVoiceCommand.call(
    manager,
    state,
    { displayName: "Owner" },
    { type: "resume" },
  );

  assert.equal(result, "Restarting Pain Remains I: Dancing Like Flames.");
  assert.deepEqual(linkedTexts, ["Restarted **Pain Remains I: Dancing Like Flames**."]);
});

test("handleGenericPlayMusic falls back to a default mix when nothing is queued", async () => {
  const state = {
    guildId: "guild-1",
    voiceChannelName: "General",
    textChannelId: "text-1",
    currentTrack: null,
    player: { state: { status: "idle" } },
    queue: [],
    lastTrack: null,
    lastRequestedQuery: "",
    pendingPlaybackQueryUserId: "",
    pendingPlaybackQueryUntil: 0,
  };
  const manager = {
    resumePlayback: async () => false,
    playNextQueuedTrack: async () => null,
    playTrack: async ({ query }) => {
      assert.equal(query, "top hits music");
      return {
        queued: false,
        track: { title: "Top Hits Mix" },
      };
    },
  };

  const result = await VoiceManager.prototype.handleGenericPlayMusic.call(
    manager,
    state,
    { id: "owner-1", displayName: "Owner" },
  );

  assert.equal(result.action, "autoplay");
  assert.equal(result.track.title, "Top Hits Mix");
  assert.equal(state.pendingPlaybackQueryUserId, "");
});

test("processVoiceTranscript turns pending playback follow-ups into play commands", async () => {
  const state = {
    guildId: "guild-1",
    voiceChannelName: "General",
    voiceChannelId: "voice-1",
    textChannelId: "text-1",
    guild: { name: "Guild" },
    ignoredUntilByUser: new Map(),
    pendingPlaybackQueryUserId: "owner-1",
    pendingPlaybackQueryUntil: Date.now() + 10_000,
  };
  const playCalls = [];
  const manager = {
    sessions: new Map([["guild-1", state]]),
    config: { voiceNoWakeCooldownMs: 8_000 },
    getVoiceWakeWords: () => ["thomas", "hey thomas"],
    isVoiceWakeWordRequired: () => false,
    isRecentSpeechEcho: () => false,
    isDuplicateTranscript: () => false,
    canUserUseCapability: () => true,
    canUserTalk: () => true,
    canUserUseMedia: () => true,
    handleNativeVoiceCommand: async () => {
      throw new Error("native voice command should not run for pending playback follow-up");
    },
    askThomasInVoice: async () => {
      throw new Error("Thomas fallback should not run for pending playback follow-up");
    },
    playTrack: async (payload) => {
      playCalls.push(payload);
      return {
        queued: false,
        track: { title: "Scary Monsters and Nice Sprites" },
      };
    },
    summarizeTrackForSpeech: VoiceManager.prototype.summarizeTrackForSpeech,
  };
  const member = {
    id: "owner-1",
    displayName: "Owner",
    user: { bot: false },
  };

  const result = await VoiceManager.prototype.processVoiceTranscript.call(manager, {
    guildId: "guild-1",
    member,
    userId: member.id,
    rawTranscript: "something from Skrillex",
  });

  assert.equal(result.handled, true);
  assert.equal(result.action, "native-play-followup");
  assert.equal(result.replyText, "Playing Scary Monsters and Nice Sprites.");
  assert.equal(playCalls.length, 1);
  assert.equal(playCalls[0].query, "something from Skrillex");
  assert.equal(state.pendingPlaybackQueryUserId, "");
});
