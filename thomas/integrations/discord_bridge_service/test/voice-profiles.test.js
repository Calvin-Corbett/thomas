import test from "node:test";
import assert from "node:assert/strict";

import {
  buildVoiceProfileChoices,
  formatVoiceProfileLabel,
  resolveVoiceProfile,
} from "../src/voice-profiles.js";

test("resolveVoiceProfile matches installed aliases", () => {
  assert.equal(resolveVoiceProfile("lessac high")?.id, "en_US-lessac-high");
  assert.equal(resolveVoiceProfile("ryan")?.id, "en_US-ryan-high");
});

test("formatVoiceProfileLabel prefers friendly labels", () => {
  assert.equal(formatVoiceProfileLabel("en_US-ryan-high"), "Ryan High");
  assert.equal(formatVoiceProfileLabel("custom-profile"), "custom-profile");
});

test("buildVoiceProfileChoices exposes known profiles", () => {
  const choices = buildVoiceProfileChoices("C:\\does-not-matter", "en_US-ryan-high");
  assert.ok(choices.some((choice) => choice.value === "en_US-ryan-high"));
  assert.ok(choices.some((choice) => choice.value === "en_US-lessac-high"));
});
