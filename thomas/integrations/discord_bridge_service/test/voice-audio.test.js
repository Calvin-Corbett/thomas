import test from "node:test";
import assert from "node:assert/strict";

import {
  createWavBuffer,
  downmixStereo48kToMono16k,
  pcmByteLengthToDurationMs,
} from "../src/voice-audio.js";

test("pcmByteLengthToDurationMs reports stereo PCM duration", () => {
  const bytes = 48_000 * 2 * 2;
  assert.equal(pcmByteLengthToDurationMs(bytes, { sampleRate: 48_000, channels: 2 }), 1000);
});

test("downmixStereo48kToMono16k averages channels and downsamples by 3", () => {
  const input = Buffer.alloc(12);
  input.writeInt16LE(3000, 0);
  input.writeInt16LE(1000, 2);
  input.writeInt16LE(111, 4);
  input.writeInt16LE(222, 6);
  input.writeInt16LE(333, 8);
  input.writeInt16LE(444, 10);

  const output = downmixStereo48kToMono16k(input);
  assert.equal(output.length, 2);
  assert.equal(output.readInt16LE(0), 2000);
});

test("createWavBuffer writes a RIFF header", () => {
  const wav = createWavBuffer(Buffer.alloc(4), {
    sampleRate: 16_000,
    channels: 1,
  });

  assert.equal(wav.toString("ascii", 0, 4), "RIFF");
  assert.equal(wav.toString("ascii", 8, 12), "WAVE");
  assert.equal(wav.toString("ascii", 36, 40), "data");
  assert.equal(wav.readUInt32LE(40), 4);
});
