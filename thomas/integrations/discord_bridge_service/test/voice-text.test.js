import test from "node:test";
import assert from "node:assert/strict";

import {
  extractWakePhrase,
  formatSpeechText,
  isWakeGreetingPhrase,
  looksLikeSpeechEcho,
  normalizeTtsText,
  shouldCooldownAfterMissedWake,
} from "../src/voice-text.js";

test("extractWakePhrase requires Thomas by default", () => {
  assert.equal(extractWakePhrase("background chatter", { wakeWords: ["thomas"] }), null);
  assert.equal(extractWakePhrase("Thomas, turn the music down", { wakeWords: ["thomas"] }), "turn the music down");
});

test("extractWakePhrase returns a friendly default when only the wake word was spoken", () => {
  assert.equal(extractWakePhrase("hey thomas", { wakeWords: ["hey thomas"] }), "hello");
});

test("extractWakePhrase allows brief filler words before the wake word", () => {
  assert.equal(
    extractWakePhrase("uh Thomas can you hear me", { wakeWords: ["thomas"] }),
    "uh can you hear me",
  );
});

test("extractWakePhrase triggers when the wake word appears later in the sentence", () => {
  assert.equal(
    extractWakePhrase("I was telling Jake that Thomas should lower the music", { wakeWords: ["thomas"] }),
    "I was telling Jake that should lower the music",
  );
});

test("extractWakePhrase still handles wake word only", () => {
  assert.equal(extractWakePhrase("Thomas", { wakeWords: ["thomas"] }), "hello");
});

test("isWakeGreetingPhrase identifies the fast local wake reply", () => {
  assert.equal(isWakeGreetingPhrase("hello"), true);
  assert.equal(isWakeGreetingPhrase("turn the music down"), false);
});

test("extractWakePhrase tolerates the common hey davis misread", () => {
  assert.equal(
    extractWakePhrase("Hey, Davis.", { wakeWords: ["thomas", "hey thomas"] }),
    "hello",
  );
});

test("extractWakePhrase prefers longer wake phrases before bare thomas", () => {
  assert.equal(
    extractWakePhrase("Hey Thomas, what's the capital of Texas?", {
      wakeWords: ["thomas", "hey thomas"],
    }),
    "what's the capital of Texas?",
  );
});

test("formatSpeechText strips markdown and shortens long replies", () => {
  const spoken = formatSpeechText(
    "Look at [this](https://example.com) and `run this` right now before you do anything else in the server.",
    40,
  );
  assert.match(spoken, /^Look at this and run this/);
  assert.ok(spoken.endsWith("..."));
});

test("normalizeTtsText expands symbols and acronyms for speech", () => {
  assert.equal(
    normalizeTtsText("GPU/API @ 75% & HDMI #2..."),
    "G P U slash A P I at 75 percent and H D M I number 2.",
  );
});

test("looksLikeSpeechEcho catches recent repeated bot lines", () => {
  assert.equal(
    looksLikeSpeechEcho(
      "say that again in one short sentence and i'll answer directly",
      "Say that again in one short sentence and I'll answer directly.",
    ),
    true,
  );
});

test("looksLikeSpeechEcho ignores unrelated speech", () => {
  assert.equal(
    looksLikeSpeechEcho(
      "turn the music down a little bit",
      "Say that again in one short sentence and I'll answer directly.",
    ),
    false,
  );
});

test("shouldCooldownAfterMissedWake catches long open-mic commentary", () => {
  assert.equal(
    shouldCooldownAfterMissedWake(
      "it felt like harrison smith but harrison smith is now thirty eight years old and that is a fumble",
      { wakeWords: ["thomas"], requireWakeWord: true },
    ),
    true,
  );
});

test("shouldCooldownAfterMissedWake ignores short commands and wake-word speech", () => {
  assert.equal(
    shouldCooldownAfterMissedWake(
      "turn the music down",
      { wakeWords: ["thomas"], requireWakeWord: true },
    ),
    false,
  );
  assert.equal(
    shouldCooldownAfterMissedWake(
      "hey thomas can you turn the music down a little bit",
      { wakeWords: ["thomas"], requireWakeWord: true },
    ),
    false,
  );
});
