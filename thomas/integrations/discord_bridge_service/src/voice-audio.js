const PCM_BYTES_PER_SAMPLE = 2;

export function pcmByteLengthToDurationMs(byteLength, { sampleRate, channels }) {
  if (!byteLength || !sampleRate || !channels) {
    return 0;
  }

  return Math.round((byteLength / (sampleRate * channels * PCM_BYTES_PER_SAMPLE)) * 1000);
}

export function downmixStereo48kToMono16k(pcmBuffer) {
  const input = Buffer.isBuffer(pcmBuffer) ? pcmBuffer : Buffer.from(pcmBuffer || []);
  const frameCount = Math.floor(input.length / 4);
  const outputSampleCount = Math.floor(frameCount / 3);
  const output = Buffer.alloc(outputSampleCount * PCM_BYTES_PER_SAMPLE);

  let outputOffset = 0;
  for (let frame = 0; frame + 2 < frameCount; frame += 3) {
    const inputOffset = frame * 4;
    const left = input.readInt16LE(inputOffset);
    const right = input.readInt16LE(inputOffset + 2);
    const mixed = Math.max(-32768, Math.min(32767, Math.round((left + right) / 2)));
    output.writeInt16LE(mixed, outputOffset);
    outputOffset += PCM_BYTES_PER_SAMPLE;
  }

  return output;
}

export function createWavBuffer(pcmBuffer, { sampleRate, channels, bitsPerSample = 16 }) {
  const pcm = Buffer.isBuffer(pcmBuffer) ? pcmBuffer : Buffer.from(pcmBuffer || []);
  const byteRate = sampleRate * channels * (bitsPerSample / 8);
  const blockAlign = channels * (bitsPerSample / 8);
  const header = Buffer.alloc(44);

  header.write("RIFF", 0, "ascii");
  header.writeUInt32LE(36 + pcm.length, 4);
  header.write("WAVE", 8, "ascii");
  header.write("fmt ", 12, "ascii");
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write("data", 36, "ascii");
  header.writeUInt32LE(pcm.length, 40);

  return Buffer.concat([header, pcm]);
}

export function pcmStereo48kToMono16kWav(pcmBuffer) {
  const mono16k = downmixStereo48kToMono16k(pcmBuffer);
  return createWavBuffer(mono16k, {
    sampleRate: 16000,
    channels: 1,
  });
}
