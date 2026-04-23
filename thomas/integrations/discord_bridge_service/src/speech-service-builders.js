import {
  OPENAI_DEFAULT_STT_MODEL,
  OPENAI_DEFAULT_TTS_MODEL,
  OPENAI_DEFAULT_VOICE,
} from "./speech-service-env.js";

function normalizeHintList(value) {
  const items = Array.isArray(value) ? value : [value];
  return [...new Set(
    items
      .map((item) => String(item || "").trim())
      .filter(Boolean),
  )];
}

export function buildOpenAiSpeechPayload({
  model = OPENAI_DEFAULT_TTS_MODEL,
  voice = OPENAI_DEFAULT_VOICE,
  input,
  responseFormat = "wav",
}) {
  return {
    model,
    voice,
    input: String(input || ""),
    response_format: responseFormat,
  };
}

export function buildOpenAiTranscriptionFormFields({
  model = OPENAI_DEFAULT_STT_MODEL,
  language = "en",
  prompt = "",
}) {
  const fields = {
    model,
    response_format: "json",
  };

  if (language) {
    fields.language = language;
  }
  if (String(prompt || "").trim()) {
    fields.prompt = String(prompt || "").trim();
  }

  return fields;
}

export function buildFasterWhisperWorkerArgs({
  workerScript,
  model,
  device,
  computeType,
  beamSize,
  vadFilter,
  vadMinSilenceMs,
  language,
}) {
  const args = [
    workerScript,
    "--model",
    model,
    "--device",
    device,
    "--compute-type",
    computeType,
    "--beam-size",
    String(beamSize),
    "--vad-filter",
    vadFilter ? "true" : "false",
    "--vad-min-silence-ms",
    String(vadMinSilenceMs),
  ];

  if (language) {
    args.push("--language", language);
  }

  return args;
}

export function buildOpenAiTranscriptionPrompt({ hotwords = [], initialPrompt = "" } = {}) {
  const parts = [];
  const normalizedPrompt = String(initialPrompt || "").trim();
  if (normalizedPrompt) {
    parts.push(normalizedPrompt);
  }

  const normalizedHotwords = normalizeHintList(hotwords);
  if (normalizedHotwords.length > 0) {
    parts.push(`Important names and phrases: ${normalizedHotwords.join(", ")}.`);
  }

  const prompt = parts.join(" ").trim();
  if (!prompt) {
    return "";
  }
  return prompt.slice(0, 400);
}

export function buildFasterWhisperRequestPayload({
  id,
  inputPath,
  hotwords = [],
  initialPrompt = "",
}) {
  const payload = {
    id,
    input_path: inputPath,
  };

  const normalizedHotwords = normalizeHintList(hotwords);
  if (normalizedHotwords.length > 0) {
    payload.hotwords = normalizedHotwords;
  }

  const normalizedPrompt = String(initialPrompt || "").trim();
  if (normalizedPrompt) {
    payload.initial_prompt = normalizedPrompt;
  }

  return payload;
}

export function buildPiperWorkerArgs({
  workerScript,
  model,
  dataDir,
  useCuda,
  speaker,
  sentencePauseMs,
  lengthScale,
  noiseScale,
  noiseWScale,
}) {
  const args = [
    workerScript,
    "--model",
    model,
    "--data-dir",
    dataDir,
  ];

  if (useCuda) {
    args.push("--cuda");
  }
  if (speaker != null) {
    args.push("--speaker", String(speaker));
  }
  if (sentencePauseMs != null) {
    args.push("--sentence-pause-ms", String(sentencePauseMs));
  }
  if (lengthScale != null) {
    args.push("--length-scale", String(lengthScale));
  }
  if (noiseScale != null) {
    args.push("--noise-scale", String(noiseScale));
  }
  if (noiseWScale != null) {
    args.push("--noise-w-scale", String(noiseWScale));
  }

  return args;
}
