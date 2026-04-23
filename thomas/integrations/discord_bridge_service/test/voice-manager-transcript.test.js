import test from "node:test";
import assert from "node:assert/strict";

import { VoiceManager } from "../src/voice-manager.js";

test("processVoiceTranscript responds to wake greeting with a spoken prompt", async () => {
  const state = {
    guildId: "guild-1",
    voiceChannelName: "General",
    voiceChannelId: "voice-1",
    guild: { name: "Guild" },
    ignoredUntilByUser: new Map(),
  };
  const spoken = [];
  const manager = {
    sessions: new Map([["guild-1", state]]),
    config: { voiceNoWakeCooldownMs: 8_000 },
    getVoiceWakeWords: () => ["thomas", "hey thomas"],
    isVoiceWakeWordRequired: () => true,
    isRecentSpeechEcho: () => false,
    isDuplicateTranscript: () => false,
    speakText: async (...args) => {
      spoken.push(args);
    },
    canUserUseCapability: () => true,
    canUserTalk: () => true,
    handleNativeVoiceCommand: async () => {
      throw new Error("native voice command should not run for wake greeting");
    },
    askThomasInVoice: async () => {
      throw new Error("Thomas prompt should not run for wake greeting");
    },
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
    rawTranscript: "Hey Thomas",
    speakOptions: { awaitPlayback: false },
  });

  assert.equal(result.handled, true);
  assert.equal(result.action, "wake-greeting");
  assert.equal(result.replyText, "Yeah?");
  assert.equal(result.transcript, "hello");
  assert.equal(spoken.length, 1);
  assert.deepEqual(spoken[0], ["guild-1", "Yeah?", { awaitPlayback: false }]);
});

test("processVoiceTranscript routes wake-word prompts into Thomas voice replies", async () => {
  const state = {
    guildId: "guild-1",
    voiceChannelName: "General",
    voiceChannelId: "voice-1",
    guild: { name: "Guild" },
    ignoredUntilByUser: new Map(),
  };
  const thomasCalls = [];
  const manager = {
    sessions: new Map([["guild-1", state]]),
    config: { voiceNoWakeCooldownMs: 8_000 },
    getVoiceWakeWords: () => ["thomas", "hey thomas"],
    isVoiceWakeWordRequired: () => true,
    isRecentSpeechEcho: () => false,
    isDuplicateTranscript: () => false,
    speakText: async () => {
      throw new Error("wake-word prompt should speak via askThomasInVoice, not direct speakText");
    },
    canUserUseCapability: () => true,
    canUserTalk: () => true,
    handleNativeVoiceCommand: async () => {
      throw new Error("native voice command should not run for Thomas reply test");
    },
    askThomasInVoice: async (payload) => {
      thomasCalls.push(payload);
      return "I'm doing well, thanks for asking.";
    },
  };
  const member = {
    id: "owner-1",
    displayName: "Owner",
    user: { bot: false },
  };
  const speakOptions = { awaitPlayback: false };

  const result = await VoiceManager.prototype.processVoiceTranscript.call(manager, {
    guildId: "guild-1",
    member,
    userId: member.id,
    rawTranscript: "Hey Thomas, how are you?",
    speakOptions,
  });

  assert.equal(result.handled, true);
  assert.equal(result.action, "thomas-reply");
  assert.equal(result.replyText, "I'm doing well, thanks for asking.");
  assert.equal(result.transcript, "how are you?");
  assert.equal(thomasCalls.length, 1);
  assert.deepEqual(thomasCalls[0], {
    guildId: "guild-1",
    speakerName: "Owner",
    speakerId: "owner-1",
    text: "how are you?",
    speakOptions,
  });
});

test("processVoiceTranscript routes wake-word native commands before Thomas chat fallback", async () => {
  const state = {
    guildId: "guild-1",
    voiceChannelName: "General",
    voiceChannelId: "voice-1",
    guild: { name: "Guild" },
    ignoredUntilByUser: new Map(),
  };
  const nativeCalls = [];
  const manager = {
    sessions: new Map([["guild-1", state]]),
    config: { voiceNoWakeCooldownMs: 8_000 },
    getVoiceWakeWords: () => ["thomas", "hey thomas"],
    isVoiceWakeWordRequired: () => true,
    isRecentSpeechEcho: () => false,
    isDuplicateTranscript: () => false,
    speakText: async () => {
      throw new Error("native voice command should not use direct wake greeting speech");
    },
    canUserUseCapability: () => true,
    canUserTalk: () => true,
    handleNativeVoiceCommand: async (...args) => {
      nativeCalls.push(args);
      return "Joined Music.";
    },
    askThomasInVoice: async () => {
      throw new Error("native voice command should not fall back to Thomas chat");
    },
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
    rawTranscript: "Hey Thomas, join the music chat",
    speakOptions: { awaitPlayback: false },
  });

  assert.equal(result.handled, true);
  assert.equal(result.action, "native-join_voice_channel");
  assert.equal(result.replyText, "Joined Music.");
  assert.equal(result.transcript, "join the music chat");
  assert.equal(nativeCalls.length, 1);
  assert.equal(nativeCalls[0][0], state);
  assert.equal(nativeCalls[0][1], member);
  assert.deepEqual(nativeCalls[0][2], {
    type: "join_voice_channel",
    targetQuery: "music",
  });
});
