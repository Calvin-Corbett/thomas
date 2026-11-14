import test from "node:test";
import assert from "node:assert/strict";

import {
  clampVolumePercent,
  formatDuration,
  formatQueueStatus,
  formatTrackLine,
  formatYouTubeResults,
  normalizeEffectName,
  parseNativeCommand,
} from "../src/native-commands.js";

test("parseNativeCommand detects youtube searches", () => {
  assert.deepEqual(
    parseNativeCommand("Hey Thomas, look up youtube video for lofi hip hop"),
    { type: "youtube_search", query: "lofi hip hop", limit: null },
  );
  assert.deepEqual(
    parseNativeCommand("Thomas, look up a YouTube video for never gonna give you up and post the top result only."),
    { type: "youtube_search", query: "never gonna give you up", limit: 1 },
  );
});

test("parseNativeCommand detects play requests and sound effects", () => {
  assert.deepEqual(
    parseNativeCommand("play never gonna give you up"),
    { type: "play", query: "never gonna give you up" },
  );
  assert.deepEqual(
    parseNativeCommand("All right, man. Well, can you play some music?"),
    { type: "play", query: "some music" },
  );
  assert.deepEqual(
    parseNativeCommand("bang"),
    { type: "effect", effect: "bang" },
  );
});

test("parseNativeCommand detects stop requests", () => {
  assert.deepEqual(parseNativeCommand("stop music"), { type: "stop" });
});

test("parseNativeCommand detects playback control requests", () => {
  assert.deepEqual(parseNativeCommand("pause music"), { type: "pause" });
  assert.deepEqual(parseNativeCommand("resume playback"), { type: "resume" });
  assert.deepEqual(parseNativeCommand("next track"), { type: "skip" });
  assert.deepEqual(parseNativeCommand("show the queue"), { type: "queue" });
  assert.deepEqual(parseNativeCommand("now playing"), { type: "status" });
  assert.deepEqual(parseNativeCommand("set volume to 135 percent"), {
    type: "volume",
    volumePercent: 135,
  });
  assert.deepEqual(parseNativeCommand("switch to lessac high voice"), {
    type: "voice_profile",
    profileId: "en_US-lessac-high",
  });
  assert.deepEqual(parseNativeCommand("reply only when mentioned"), {
    type: "set_text_mentions",
    requireMention: true,
  });
  assert.deepEqual(parseNativeCommand("reply to everyone"), {
    type: "set_text_mentions",
    requireMention: false,
  });
  assert.deepEqual(parseNativeCommand("require wake word"), {
    type: "set_voice_wake_required",
    requireWakeWord: true,
  });
  assert.deepEqual(parseNativeCommand("wake word off"), {
    type: "set_voice_wake_required",
    requireWakeWord: false,
  });
  assert.deepEqual(parseNativeCommand("set wake words to thomas, hey thomas and yo thomas"), {
    type: "set_voice_wake_words",
    wakeWords: ["thomas", "hey thomas", "yo thomas"],
  });
  assert.deepEqual(parseNativeCommand("allow <@123456789> to use music and chat"), {
    type: "access_grant",
    targetUserId: "123456789",
    targetQuery: null,
    capabilities: ["talk", "media"],
  });
  assert.deepEqual(parseNativeCommand("give Wolves1289 music access"), {
    type: "access_grant",
    targetUserId: null,
    targetQuery: "Wolves1289",
    capabilities: ["media"],
  });
  assert.deepEqual(parseNativeCommand("revoke <@123456789> access"), {
    type: "access_revoke",
    targetUserId: "123456789",
    targetQuery: null,
  });
  assert.deepEqual(parseNativeCommand("list thomas access"), {
    type: "access_list",
  });
  assert.deepEqual(parseNativeCommand("join the music chat"), {
    type: "join_voice_channel",
    targetQuery: "music",
  });
  assert.deepEqual(parseNativeCommand("leave the voice chat"), {
    type: "leave_voice_channel",
  });
});

test("normalizeEffectName resolves aliases", () => {
  assert.equal(normalizeEffectName("air horn"), "airhorn");
  assert.equal(normalizeEffectName("unknown"), null);
});

test("format helpers keep media replies readable", () => {
  assert.equal(formatDuration(125), "2:05");
  assert.equal(clampVolumePercent(250), 200);
  assert.match(
    formatTrackLine(
      {
        title: "Example Song",
        durationSeconds: 125,
        channel: "Example Channel",
        webpageUrl: "https://youtube.com/watch?v=123",
      },
      1,
    ),
    /1\. Example Song \(2:05\) - Example Channel/,
  );
  assert.match(
    formatYouTubeResults("example", [
      {
        title: "Example Song",
        durationSeconds: 125,
        channel: "Example Channel",
        webpageUrl: "https://youtube.com/watch?v=123",
      },
      {
        title: "Another Song",
        durationSeconds: 200,
        channel: "Another Channel",
        webpageUrl: "https://youtube.com/watch?v=456",
      },
    ]),
    /YouTube results for "example":/,
  );
  assert.match(
    formatYouTubeResults("example", [
      {
        title: "Example Song",
        durationSeconds: 125,
        channel: "Example Channel",
        webpageUrl: "https://youtube.com/watch?v=123",
      },
    ]),
    /Top YouTube result for "example":/,
  );
  assert.match(
    formatQueueStatus({
      currentTrack: {
        title: "Example Song",
        durationSeconds: 125,
        channel: "Example Channel",
        webpageUrl: "https://youtube.com/watch?v=123",
      },
      queue: [
        {
          title: "Another Song",
          durationSeconds: 200,
          channel: "Another Channel",
          webpageUrl: "https://youtube.com/watch?v=456",
        },
      ],
      paused: false,
      volumePercent: 110,
    }),
    /Now playing:/,
  );
});
