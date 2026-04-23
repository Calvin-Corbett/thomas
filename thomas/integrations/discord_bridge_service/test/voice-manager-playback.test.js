import test from "node:test";
import assert from "node:assert/strict";

import { VoiceManager } from "../src/voice-manager.js";

test("handleNativeVoiceCommand reuses paused playback for generic play music", async () => {
  const state = {
    guildId: "guild-1",
    voiceChannelName: "General",
    textChannelId: "text-1",
    currentTrack: { title: "Lose Yourself", webpageUrl: "https://youtube.com/watch?v=123" },
    player: { state: { status: "paused" } },
    queue: [],
    lastTrack: null,
    lastRequestedQuery: "",
  };
  const linkedTexts = [];
  const manager = {
    resumePlayback: async () => true,
    playNextQueuedTrack: async () => null,
    playTrack: async () => {
      throw new Error("generic play should resume before replaying a query");
    },
    sendLinkedText: async (_state, text) => {
      linkedTexts.push(text);
    },
    summarizeTrackForSpeech: VoiceManager.prototype.summarizeTrackForSpeech,
    handleGenericPlayMusic: VoiceManager.prototype.handleGenericPlayMusic,
  };

  const result = await VoiceManager.prototype.handleNativeVoiceCommand.call(
    manager,
    state,
    { displayName: "Owner" },
    { type: "play_music" },
  );

  assert.equal(result, "Resumed Lose Yourself.");
  assert.deepEqual(linkedTexts, ["Resumed **Lose Yourself**."]);
});

test("handleNativeVoiceCommand switches immediately for explicit play requests in voice", async () => {
  const state = {
    guildId: "guild-1",
    voiceChannelName: "General",
    textChannelId: "text-1",
    currentTrack: { title: "Wrong Song" },
    currentPlaybackProcess: { pid: 1234 },
    queue: [{ track: { title: "Old queued song" } }],
    player: { state: { status: "playing" } },
  };
  const linkedTexts = [];
  const playCalls = [];
  const manager = {
    playTrack: async (payload) => {
      playCalls.push(payload);
      return {
        queued: false,
        replaced: true,
        track: { title: "Pain Remains" },
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
    { type: "play", query: "pain remains" },
  );

  assert.equal(result, "Switching to Pain Remains.");
  assert.equal(playCalls.length, 1);
  assert.equal(playCalls[0].interruptCurrent, true);
  assert.equal(playCalls[0].clearQueue, true);
  assert.deepEqual(linkedTexts, ["Switching to **Pain Remains** now."]);
});

test("handleNativeVoiceCommand keeps explicit queue requests in the queue lane", async () => {
  const state = {
    guildId: "guild-1",
    voiceChannelName: "General",
    textChannelId: "text-1",
  };
  const linkedTexts = [];
  const playCalls = [];
  const manager = {
    playTrack: async (payload) => {
      playCalls.push(payload);
      return {
        queued: true,
        position: 2,
        track: { title: "Pain Remains" },
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
    { type: "queue_track", query: "pain remains" },
  );

  assert.equal(result, "Queued Pain Remains.");
  assert.equal(playCalls.length, 1);
  assert.equal(Boolean(playCalls[0].interruptCurrent), false);
  assert.deepEqual(linkedTexts, ["Queued **Pain Remains** at position 2."]);
});
