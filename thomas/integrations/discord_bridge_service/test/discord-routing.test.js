import test from "node:test";
import assert from "node:assert/strict";

import { buildTextWakePhrases, isTextAddressedToBot } from "../src/discord-routing.js";

test("buildTextWakePhrases includes bot names and configured wake words", () => {
  const phrases = buildTextWakePhrases({
    botNames: ["Thomas"],
    configuredWakeWords: ["hey thomas"],
  });

  assert.ok(phrases.includes("thomas"));
  assert.ok(phrases.includes("hey thomas"));
  assert.ok(phrases.includes("yo thomas"));
});

test("isTextAddressedToBot detects direct text wake phrases", () => {
  const options = {
    botNames: ["Thomas"],
    configuredWakeWords: ["hey thomas"],
  };

  assert.equal(isTextAddressedToBot("Thomas, play never gonna give you up", options), true);
  assert.equal(isTextAddressedToBot("hey thomas can you hear me", options), true);
  assert.equal(isTextAddressedToBot("yo thomas bang", options), true);
  assert.equal(isTextAddressedToBot("this is just regular chat", options), false);
  assert.equal(isTextAddressedToBot("I think Thomas sounds better now", options), false);
});
