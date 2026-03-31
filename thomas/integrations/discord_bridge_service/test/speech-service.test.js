import test from "node:test";
import assert from "node:assert/strict";

import {
  buildSpeechEnv,
  buildFasterWhisperWorkerArgs,
  buildFasterWhisperRequestPayload,
  buildOpenAiSpeechPayload,
  buildOpenAiTranscriptionPrompt,
  buildOpenAiTranscriptionFormFields,
  buildPiperWorkerArgs,
  normalizeSttBackend,
  normalizeTtsBackend,
  resolveCommandPath,
  resolvePowerShellCommand,
} from "../src/speech-service.js";

test("normalizeSttBackend prefers faster-whisper by default", () => {
  assert.equal(normalizeSttBackend(""), "faster-whisper");
  assert.equal(normalizeSttBackend("faster_whisper"), "faster-whisper");
  assert.equal(normalizeSttBackend("windows"), "windows");
  assert.equal(normalizeSttBackend("openai"), "openai");
});

test("normalizeTtsBackend prefers piper by default", () => {
  assert.equal(normalizeTtsBackend(""), "piper");
  assert.equal(normalizeTtsBackend("piper"), "piper");
  assert.equal(normalizeTtsBackend("windows"), "windows");
  assert.equal(normalizeTtsBackend("cloud"), "openai");
});

test("buildFasterWhisperWorkerArgs includes the configured worker settings", () => {
  const args = buildFasterWhisperWorkerArgs({
    workerScript: "C:\\worker.py",
    model: "distil-large-v3",
    device: "cuda",
    computeType: "float16",
    beamSize: 5,
    vadFilter: true,
    vadMinSilenceMs: 500,
    language: "en",
  });

  assert.deepEqual(args, [
    "C:\\worker.py",
    "--model",
    "distil-large-v3",
    "--device",
    "cuda",
    "--compute-type",
    "float16",
    "--beam-size",
    "5",
    "--vad-filter",
    "true",
    "--vad-min-silence-ms",
    "500",
    "--language",
    "en",
  ]);
});

test("buildFasterWhisperRequestPayload includes hint phrases when provided", () => {
  const payload = buildFasterWhisperRequestPayload({
    id: "abc",
    inputPath: "C:\\clip.wav",
    hotwords: ["Thomas", "hey Thomas", "Thomas"],
    initialPrompt: "The assistant name is Thomas.",
  });

  assert.deepEqual(payload, {
    id: "abc",
    input_path: "C:\\clip.wav",
    hotwords: ["Thomas", "hey Thomas"],
    initial_prompt: "The assistant name is Thomas.",
  });
});

test("resolveCommandPath resolves repo-local executables", () => {
  const resolved = resolveCommandPath(".venv\\Scripts\\python.exe");
  assert.equal(
    resolved.endsWith("\\.venv\\Scripts\\python.exe")
      || resolved.endsWith("/.venv/Scripts/python.exe"),
    true,
  );
  assert.equal(/discord_bridge_service[\\/]+\.venv/i.test(resolved), false);
});

test("resolvePowerShellCommand prefers the explicit Windows PowerShell path", () => {
  const resolved = resolvePowerShellCommand({ SystemRoot: "C:\\Windows" });
  assert.equal(
    resolved.endsWith("\\WindowsPowerShell\\v1.0\\powershell.exe") || resolved === "powershell.exe",
    true,
  );
});

test("buildSpeechEnv prepends torch and onnxruntime library paths", () => {
  const env = buildSpeechEnv({ PATH: "C:\\Windows\\System32" });
  const pathValue = env.PATH;

  assert.match(pathValue, /torch[\\/]+lib/i);
  assert.match(pathValue, /onnxruntime[\\/]+capi/i);
  assert.match(pathValue, /C:\\Windows\\System32/i);
});

test("buildPiperWorkerArgs includes voice settings", () => {
  const args = buildPiperWorkerArgs({
    workerScript: "C:\\piper-worker.py",
    model: "en_US-ryan-high",
    dataDir: "C:\\voices",
    useCuda: false,
    speaker: null,
    sentencePauseMs: 140,
    lengthScale: null,
    noiseScale: null,
    noiseWScale: null,
  });

  assert.deepEqual(args, [
    "C:\\piper-worker.py",
    "--model",
    "en_US-ryan-high",
    "--data-dir",
    "C:\\voices",
    "--sentence-pause-ms",
    "140",
  ]);
});

test("buildOpenAiSpeechPayload uses the expected audio speech fields", () => {
  assert.deepEqual(
    buildOpenAiSpeechPayload({
      model: "gpt-4o-mini-tts",
      voice: "alloy",
      input: "hello there",
      responseFormat: "wav",
    }),
    {
      model: "gpt-4o-mini-tts",
      voice: "alloy",
      input: "hello there",
      response_format: "wav",
    },
  );
});

test("buildOpenAiTranscriptionFormFields sets model and language", () => {
  assert.deepEqual(
    buildOpenAiTranscriptionFormFields({
      model: "gpt-4o-transcribe",
      language: "en",
      prompt: "Important names and phrases: Thomas, hey Thomas.",
    }),
    {
      model: "gpt-4o-transcribe",
      response_format: "json",
      language: "en",
      prompt: "Important names and phrases: Thomas, hey Thomas.",
    },
  );
});

test("buildOpenAiTranscriptionPrompt combines prompt context with hotwords", () => {
  assert.equal(
    buildOpenAiTranscriptionPrompt({
      initialPrompt: "The assistant name is Thomas.",
      hotwords: ["Thomas", "hey Thomas", "Thomas"],
    }),
    "The assistant name is Thomas. Important names and phrases: Thomas, hey Thomas.",
  );
});

test("cloud backend names are available through normalization", () => {
  assert.equal(normalizeTtsBackend("openai"), "openai");
  assert.equal(normalizeSttBackend("cloud"), "openai");
});
