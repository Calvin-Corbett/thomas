import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import fs from "node:fs";
import fsPromises from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import readline from "node:readline";
import { fileURLToPath } from "node:url";

const OPENAI_BASE_URL = "https://api.openai.com/v1";
const OPENAI_DEFAULT_TTS_MODEL = "gpt-4o-mini-tts";
const OPENAI_DEFAULT_STT_MODEL = "gpt-4o-mini-transcribe";
const OPENAI_DEFAULT_VOICE = "alloy";
const TTS_BACKEND_PIPER = "piper";
const TTS_BACKEND_OPENAI = "openai";
const TTS_BACKEND_WINDOWS = "windows";
const STT_BACKEND_FASTER_WHISPER = "faster-whisper";
const STT_BACKEND_OPENAI = "openai";
const STT_BACKEND_WINDOWS = "windows";
const STT_STARTUP_TIMEOUT_MS = 10 * 60_000;
const TTS_STARTUP_TIMEOUT_MS = 10 * 60_000;
const DEFAULT_PROJECT_ROOT = path.resolve(fileURLToPath(new URL("../../../../", import.meta.url)));

function getProjectRoot(baseEnv = process.env) {
  return path.resolve(String(baseEnv.THOMAS_PROJECT_ROOT || DEFAULT_PROJECT_ROOT).trim() || DEFAULT_PROJECT_ROOT);
}

function appendPathEntries(existingPath, extraEntries) {
  const delimiter = process.platform === "win32" ? ";" : ":";
  const values = [
    ...extraEntries.filter(Boolean),
    ...String(existingPath || "")
      .split(delimiter)
      .map((entry) => entry.trim())
      .filter(Boolean),
  ];

  const unique = [];
  const seen = new Set();
  for (const value of values) {
    const normalized = process.platform === "win32" ? value.toLowerCase() : value;
    if (seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    unique.push(value);
  }

  return unique.join(delimiter);
}

export function buildSpeechEnv(baseEnv = process.env) {
  const env = { ...baseEnv };
  const projectRoot = getProjectRoot(baseEnv);
  const extraEntries = [
    path.resolve(projectRoot, ".venv", "Lib", "site-packages", "torch", "lib"),
    path.resolve(projectRoot, ".venv", "Lib", "site-packages", "onnxruntime", "capi"),
  ];

  env.PATH = appendPathEntries(env.PATH, extraEntries);
  return env;
}

function runCommand(command, args, timeoutMs, { cwd, stdinText } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      windowsHide: true,
      cwd,
      env: buildSpeechEnv(process.env),
    });

    let stdout = "";
    let stderr = "";
    let timedOut = false;

    const timeout = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, timeoutMs);

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.on("close", (code) => {
      clearTimeout(timeout);
      if (timedOut) {
        reject(new Error(`${path.basename(command)} timed out`));
        return;
      }
      if (code !== 0) {
        reject(new Error((stderr || stdout || `${path.basename(command)} exited with code ${code}`).trim()));
        return;
      }
      resolve({ stdout: stdout.trim(), stderr: stderr.trim() });
    });

    if (stdinText != null) {
      child.stdin.end(stdinText, "utf8");
    }
  });
}

function runPowerShellFile(scriptPath, args, timeoutMs) {
  return runCommand(
    resolvePowerShellCommand(process.env),
    ["-NoLogo", "-NonInteractive", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", scriptPath, ...args],
    timeoutMs,
  );
}

function buildWorkerReadyError(stderrTail, fallbackMessage) {
  const details = stderrTail ? `: ${stderrTail}` : "";
  return new Error(`${fallbackMessage}${details}`);
}

export function resolveCommandPath(command) {
  if (!command || path.isAbsolute(command)) {
    return command;
  }

  if (command.includes("\\") || command.includes("/")) {
    return path.resolve(getProjectRoot(process.env), command);
  }

  return command;
}

export function resolvePowerShellCommand(baseEnv = process.env) {
  if (process.platform !== "win32") {
    return "powershell";
  }

  const systemRoot = String(baseEnv.SystemRoot || baseEnv.WINDIR || "C:\\Windows").trim() || "C:\\Windows";
  const candidates = [
    path.join(systemRoot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
    path.join(systemRoot, "Sysnative", "WindowsPowerShell", "v1.0", "powershell.exe"),
    "powershell.exe",
  ];

  for (const candidate of candidates) {
    if (!candidate.toLowerCase().endsWith(".exe") || fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return "powershell.exe";
}

export function normalizeSttBackend(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["openai", "cloud"].includes(normalized)) {
    return STT_BACKEND_OPENAI;
  }
  if (["windows", "system.speech", "sapi"].includes(normalized)) {
    return STT_BACKEND_WINDOWS;
  }
  return STT_BACKEND_FASTER_WHISPER;
}

export function normalizeTtsBackend(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["openai", "cloud"].includes(normalized)) {
    return TTS_BACKEND_OPENAI;
  }
  if (["windows", "system.speech", "sapi"].includes(normalized)) {
    return TTS_BACKEND_WINDOWS;
  }
  return TTS_BACKEND_PIPER;
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

function normalizeHintList(value) {
  const items = Array.isArray(value) ? value : [value];
  return [...new Set(
    items
      .map((item) => String(item || "").trim())
      .filter(Boolean),
  )];
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

export class SpeechService {
  constructor({
    voiceName = null,
    synthTimeoutMs = 45_000,
    transcribeTimeoutMs = 90_000,
    ttsBackend = TTS_BACKEND_PIPER,
    ttsPythonBin = "python",
    ttsModel = null,
    ttsDataDir = path.resolve(
      String(process.env.DISCORD_VOICE_TTS_DATA_DIR || path.join(getProjectRoot(process.env), "runtime", "discord_bridge", "piper-voices")).trim(),
    ),
    ttsUseCuda = false,
    ttsSpeaker = null,
    ttsSentencePauseMs = 140,
    ttsLengthScale = null,
    ttsNoiseScale = null,
    ttsNoiseWScale = null,
    sttBackend = STT_BACKEND_FASTER_WHISPER,
    sttPythonBin = "python",
    sttModel = null,
    sttDevice = "cuda",
    sttComputeType = "float16",
    sttBeamSize = 5,
    sttVadFilter = true,
    sttVadMinSilenceMs = 500,
    sttLanguage = "en",
    openAiApiKey = process.env.DISCORD_VOICE_OPENAI_API_KEY || process.env.THOMAS_MODELS_OPENAI_API_KEY || process.env.OPENAI_API_KEY || null,
    openAiBaseUrl = process.env.DISCORD_VOICE_OPENAI_BASE_URL || process.env.THOMAS_MODELS_OPENAI_BASE_URL || process.env.OPENAI_BASE_URL || OPENAI_BASE_URL,
    openAiVoice = OPENAI_DEFAULT_VOICE,
    openAiResponseFormat = "wav",
  } = {}) {
    const projectRoot = getProjectRoot(process.env);
    this.voiceName = voiceName;
    this.synthTimeoutMs = synthTimeoutMs;
    this.transcribeTimeoutMs = transcribeTimeoutMs;
    this.ttsBackend = normalizeTtsBackend(ttsBackend);
    this.ttsPythonBin = ttsPythonBin;
    this.ttsModel = ttsModel || (this.ttsBackend === TTS_BACKEND_OPENAI ? OPENAI_DEFAULT_TTS_MODEL : "en_US-ryan-high");
    this.ttsDataDir = path.resolve(projectRoot, ttsDataDir);
    this.ttsUseCuda = ttsUseCuda;
    this.ttsSpeaker = ttsSpeaker;
    this.ttsSentencePauseMs = ttsSentencePauseMs;
    this.ttsLengthScale = ttsLengthScale;
    this.ttsNoiseScale = ttsNoiseScale;
    this.ttsNoiseWScale = ttsNoiseWScale;
    this.sttBackend = normalizeSttBackend(sttBackend);
    this.sttPythonBin = sttPythonBin;
    this.sttModel = sttModel || (this.sttBackend === STT_BACKEND_OPENAI ? OPENAI_DEFAULT_STT_MODEL : "distil-large-v3");
    this.sttDevice = sttDevice;
    this.sttComputeType = sttComputeType;
    this.requestedSttDevice = sttDevice;
    this.requestedSttComputeType = sttComputeType;
    this.sttBeamSize = sttBeamSize;
    this.sttVadFilter = sttVadFilter;
    this.sttVadMinSilenceMs = sttVadMinSilenceMs;
    this.sttLanguage = sttLanguage;
    this.openAiApiKey = String(openAiApiKey || "").trim() || null;
    this.openAiBaseUrl = String(openAiBaseUrl || OPENAI_BASE_URL).trim().replace(/\/+$/, "");
    this.openAiVoice = String(openAiVoice || OPENAI_DEFAULT_VOICE).trim() || OPENAI_DEFAULT_VOICE;
    this.openAiResponseFormat = String(openAiResponseFormat || "wav").trim() || "wav";
    this.cpuFallbackActive = false;
    this.loggedCloudSttReady = false;
    this.loggedCloudTtsReady = false;
    this.synthScript = fileURLToPath(new URL("../scripts/synthesize-wav.ps1", import.meta.url));
    this.transcribeScript = fileURLToPath(new URL("../scripts/transcribe-wav.ps1", import.meta.url));
    this.sttWorkerScript = fileURLToPath(new URL("../scripts/faster-whisper-worker.py", import.meta.url));
    this.ttsWorkerScript = fileURLToPath(new URL("../scripts/piper-tts-worker.py", import.meta.url));

    this.sttWorker = null;
    this.sttWorkerLineReader = null;
    this.sttWorkerReadyPromise = null;
    this.sttWorkerReadyInfo = null;
    this.sttWorkerStderrTail = "";
    this.sttPendingRequests = new Map();

    this.ttsWorker = null;
    this.ttsWorkerLineReader = null;
    this.ttsWorkerReadyPromise = null;
    this.ttsWorkerReadyInfo = null;
    this.ttsWorkerStderrTail = "";
    this.ttsPendingRequests = new Map();
  }

  createTempWavePath(prefix) {
    return path.join(os.tmpdir(), `${prefix}-${randomUUID()}.wav`);
  }

  describeTranscriber() {
    if (this.sttBackend === STT_BACKEND_WINDOWS) {
      return "windows System.Speech";
    }
    if (this.sttBackend === STT_BACKEND_OPENAI) {
      return `openai (${this.sttModel})`;
    }

    const fallback = this.cpuFallbackActive ? ", cpu fallback active" : "";
    return `${this.sttBackend} (${this.sttModel} on ${this.sttDevice}, ${this.sttComputeType}${fallback})`;
  }

  describeSynthesizer() {
    if (this.ttsBackend === TTS_BACKEND_WINDOWS) {
      return `windows System.Speech${this.voiceName ? ` (${this.voiceName})` : ""}`;
    }
    if (this.ttsBackend === TTS_BACKEND_OPENAI) {
      return `openai (${this.ttsModel}, ${this.openAiVoice})`;
    }

    return `${this.ttsBackend} (${this.ttsModel}${this.ttsUseCuda ? ", cuda" : ""})`;
  }

  async synthesizeToWav(text) {
    const outputPath = this.createTempWavePath("thomas-voice-out");
    if (this.ttsBackend === TTS_BACKEND_OPENAI) {
      await this.synthesizeWithOpenAi(text, outputPath);
      return outputPath;
    }
    if (this.ttsBackend === TTS_BACKEND_PIPER) {
      await this.synthesizeWithPiper(text, outputPath);
      return outputPath;
    }

    const args = ["-Text", String(text || ""), "-OutputPath", outputPath];
    if (this.voiceName) {
      args.push("-VoiceName", this.voiceName);
    }

    await runPowerShellFile(this.synthScript, args, this.synthTimeoutMs);
    return outputPath;
  }

  async transcribeWav(inputPath, options = {}) {
    if (this.sttBackend === STT_BACKEND_OPENAI) {
      return this.transcribeWithOpenAi(inputPath, options);
    }
    if (this.sttBackend === STT_BACKEND_WINDOWS) {
      const result = await runPowerShellFile(this.transcribeScript, ["-InputPath", inputPath], this.transcribeTimeoutMs);
      return result.stdout.trim();
    }

    try {
      return await this.transcribeWithWorker(inputPath, options);
    } catch (error) {
      if (this.shouldRetryOnCpu(error)) {
        this.enableCpuFallback(error);
        return this.transcribeWithWorker(inputPath, options);
      }
      throw error;
    }
  }

  getOpenAiHeaders(includeContentType = false) {
    if (!this.openAiApiKey) {
      throw new Error("OpenAI voice backend requires OPENAI_API_KEY or DISCORD_VOICE_OPENAI_API_KEY.");
    }

    const headers = {
      Authorization: `Bearer ${this.openAiApiKey}`,
    };
    if (includeContentType) {
      headers["Content-Type"] = "application/json";
    }
    return headers;
  }

  logCloudReady(kind) {
    if (kind === "stt") {
      if (this.loggedCloudSttReady) {
        return;
      }
      this.loggedCloudSttReady = true;
      console.log(`[thomas-discord] Voice STT ready: openai ${this.sttModel}`);
      return;
    }

    if (this.loggedCloudTtsReady) {
      return;
    }
    this.loggedCloudTtsReady = true;
    console.log(`[thomas-discord] Voice TTS ready: openai ${this.ttsModel} (${this.openAiVoice})`);
  }

  async synthesizeWithOpenAi(text, outputPath) {
    this.logCloudReady("tts");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.synthTimeoutMs);

    try {
      const response = await fetch(`${this.openAiBaseUrl}/audio/speech`, {
        method: "POST",
        headers: this.getOpenAiHeaders(true),
        signal: controller.signal,
        body: JSON.stringify(
          buildOpenAiSpeechPayload({
            model: this.ttsModel,
            voice: this.openAiVoice || this.voiceName || OPENAI_DEFAULT_VOICE,
            input: text,
            responseFormat: this.openAiResponseFormat,
          }),
        ),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`OpenAI TTS returned HTTP ${response.status}: ${errorText.slice(0, 400)}`);
      }

      const arrayBuffer = await response.arrayBuffer();
      await fsPromises.writeFile(outputPath, Buffer.from(arrayBuffer));
    } finally {
      clearTimeout(timeout);
    }
  }

  async transcribeWithOpenAi(inputPath, options = {}) {
    this.logCloudReady("stt");
    const form = new FormData();
    const fileBytes = await fsPromises.readFile(inputPath);
    form.set("file", new Blob([fileBytes], { type: "audio/wav" }), path.basename(inputPath));

    const fields = buildOpenAiTranscriptionFormFields({
      model: this.sttModel,
      language: this.sttLanguage,
      prompt: buildOpenAiTranscriptionPrompt(options),
    });
    for (const [key, value] of Object.entries(fields)) {
      form.set(key, String(value));
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.transcribeTimeoutMs);

    try {
      const response = await fetch(`${this.openAiBaseUrl}/audio/transcriptions`, {
        method: "POST",
        headers: this.getOpenAiHeaders(false),
        signal: controller.signal,
        body: form,
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`OpenAI STT returned HTTP ${response.status}: ${errorText.slice(0, 400)}`);
      }

      const contentType = String(response.headers.get("content-type") || "").toLowerCase();
      if (contentType.includes("application/json")) {
        const json = await response.json();
        return String(json.text || "").trim();
      }

      return String(await response.text()).trim();
    } finally {
      clearTimeout(timeout);
    }
  }

  async transcribeWithWorker(inputPath, { hotwords = [], initialPrompt = "" } = {}) {
    const worker = await this.ensureSttWorker();
    const id = randomUUID();

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.sttPendingRequests.delete(id);
        reject(new Error(`Local STT timed out after ${this.transcribeTimeoutMs}ms`));
      }, this.transcribeTimeoutMs);

      this.sttPendingRequests.set(id, {
        resolve: (text) => {
          clearTimeout(timeout);
          resolve(text);
        },
        reject: (error) => {
          clearTimeout(timeout);
          reject(error);
        },
      });

      const payload = buildFasterWhisperRequestPayload({
        id,
        inputPath,
        hotwords,
        initialPrompt,
      });

      worker.stdin.write(`${JSON.stringify(payload)}\n`, "utf8", (error) => {
        if (!error) {
          return;
        }
        const pending = this.sttPendingRequests.get(id);
        if (!pending) {
          return;
        }
        this.sttPendingRequests.delete(id);
        pending.reject(error);
      });
    });
  }

  async ensureSttWorker() {
    if (this.sttWorkerReadyPromise) {
      await this.sttWorkerReadyPromise;
      return this.sttWorker;
    }

    const args = buildFasterWhisperWorkerArgs({
      workerScript: this.sttWorkerScript,
      model: this.sttModel,
      device: this.sttDevice,
      computeType: this.sttComputeType,
      beamSize: this.sttBeamSize,
      vadFilter: this.sttVadFilter,
      vadMinSilenceMs: this.sttVadMinSilenceMs,
      language: this.sttLanguage,
    });

    const child = spawn(resolveCommandPath(this.sttPythonBin), args, {
      windowsHide: true,
      cwd: path.dirname(this.sttWorkerScript),
      env: buildSpeechEnv(process.env),
    });

    this.sttWorker = child;
    this.sttWorkerStderrTail = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");

    child.stderr.on("data", (chunk) => {
      this.sttWorkerStderrTail = `${this.sttWorkerStderrTail}${chunk}`.slice(-4000);
    });

    this.sttWorkerLineReader = readline.createInterface({
      input: child.stdout,
      crlfDelay: Infinity,
    });

    this.sttWorkerReadyPromise = new Promise((resolve, reject) => {
      let settled = false;
      const readyTimeout = setTimeout(() => {
        const error = buildWorkerReadyError(
          this.sttWorkerStderrTail,
          `Local STT worker timed out after ${STT_STARTUP_TIMEOUT_MS}ms`,
        );
        this.stopSttWorker();
        if (!settled) {
          settled = true;
          this.sttWorkerReadyPromise = null;
          reject(error);
        }
      }, STT_STARTUP_TIMEOUT_MS);

      const failStartup = (error) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(readyTimeout);
        this.sttWorkerReadyPromise = null;
        reject(error);
      };

      this.sttWorkerLineReader.on("line", (line) => {
        const trimmed = String(line || "").trim();
        if (!trimmed) {
          return;
        }

        let message;
        try {
          message = JSON.parse(trimmed);
        } catch {
          failStartup(new Error(`Local STT worker emitted invalid output: ${trimmed}`));
          this.stopSttWorker();
          return;
        }

        if (message.type === "ready") {
          this.sttWorkerReadyInfo = message;
          clearTimeout(readyTimeout);
          if (!settled) {
            settled = true;
            this.sttWorkerReadyPromise = Promise.resolve(child);
            console.log(
              `[thomas-discord] Voice STT ready: ${message.backend} ${message.model} on ${message.device} (${message.compute_type})`,
            );
            resolve(child);
          }
          return;
        }

        this.handleSttWorkerMessage(message);
      });

      child.once("error", (error) => {
        const startupError = buildWorkerReadyError(this.sttWorkerStderrTail, error.message);
        this.clearSttWorkerState();
        this.rejectPendingRequests(this.sttPendingRequests, startupError);
        failStartup(startupError);
      });

      child.once("close", (code) => {
        const message = code === 0
          ? "Local STT worker exited unexpectedly."
          : `Local STT worker exited with code ${code}.`;
        const startupError = buildWorkerReadyError(this.sttWorkerStderrTail, message);
        this.clearSttWorkerState();
        this.rejectPendingRequests(this.sttPendingRequests, startupError);
        failStartup(startupError);
      });
    });

    await this.sttWorkerReadyPromise;
    return child;
  }

  async synthesizeWithPiper(text, outputPath) {
    const worker = await this.ensureTtsWorker();
    const id = randomUUID();

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.ttsPendingRequests.delete(id);
        reject(new Error(`Local TTS timed out after ${this.synthTimeoutMs}ms`));
      }, this.synthTimeoutMs);

      this.ttsPendingRequests.set(id, {
        resolve: () => {
          clearTimeout(timeout);
          resolve();
        },
        reject: (error) => {
          clearTimeout(timeout);
          reject(error);
        },
      });

      worker.stdin.write(
        `${JSON.stringify({ id, text: String(text || ""), output_path: outputPath })}\n`,
        "utf8",
        (error) => {
          if (!error) {
            return;
          }
          const pending = this.ttsPendingRequests.get(id);
          if (!pending) {
            return;
          }
          this.ttsPendingRequests.delete(id);
          pending.reject(error);
        },
      );
    });
  }

  async ensureTtsWorker() {
    if (this.ttsWorkerReadyPromise) {
      await this.ttsWorkerReadyPromise;
      return this.ttsWorker;
    }

    const args = buildPiperWorkerArgs({
      workerScript: this.ttsWorkerScript,
      model: this.ttsModel,
      dataDir: this.ttsDataDir,
      useCuda: this.ttsUseCuda,
      speaker: this.ttsSpeaker,
      sentencePauseMs: this.ttsSentencePauseMs,
      lengthScale: this.ttsLengthScale,
      noiseScale: this.ttsNoiseScale,
      noiseWScale: this.ttsNoiseWScale,
    });

    const child = spawn(resolveCommandPath(this.ttsPythonBin), args, {
      windowsHide: true,
      cwd: path.dirname(this.ttsWorkerScript),
      env: buildSpeechEnv(process.env),
    });

    this.ttsWorker = child;
    this.ttsWorkerStderrTail = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => {
      this.ttsWorkerStderrTail = `${this.ttsWorkerStderrTail}${chunk}`.slice(-4000);
    });

    this.ttsWorkerLineReader = readline.createInterface({
      input: child.stdout,
      crlfDelay: Infinity,
    });

    this.ttsWorkerReadyPromise = new Promise((resolve, reject) => {
      let settled = false;
      const readyTimeout = setTimeout(() => {
        const error = buildWorkerReadyError(
          this.ttsWorkerStderrTail,
          `Local TTS worker timed out after ${TTS_STARTUP_TIMEOUT_MS}ms`,
        );
        this.stopTtsWorker();
        if (!settled) {
          settled = true;
          this.ttsWorkerReadyPromise = null;
          reject(error);
        }
      }, TTS_STARTUP_TIMEOUT_MS);

      const failStartup = (error) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(readyTimeout);
        this.ttsWorkerReadyPromise = null;
        reject(error);
      };

      this.ttsWorkerLineReader.on("line", (line) => {
        const trimmed = String(line || "").trim();
        if (!trimmed) {
          return;
        }

        let message;
        try {
          message = JSON.parse(trimmed);
        } catch {
          failStartup(new Error(`Local TTS worker emitted invalid output: ${trimmed}`));
          this.stopTtsWorker();
          return;
        }

        if (message.type === "ready") {
          this.ttsWorkerReadyInfo = message;
          clearTimeout(readyTimeout);
          if (!settled) {
            settled = true;
            this.ttsWorkerReadyPromise = Promise.resolve(child);
            console.log(`[thomas-discord] Voice TTS ready: ${message.backend} ${message.model}`);
            resolve(child);
          }
          return;
        }

        this.handleTtsWorkerMessage(message);
      });

      child.once("error", (error) => {
        const startupError = buildWorkerReadyError(this.ttsWorkerStderrTail, error.message);
        this.clearTtsWorkerState();
        this.rejectPendingRequests(this.ttsPendingRequests, startupError);
        failStartup(startupError);
      });

      child.once("close", (code) => {
        const message = code === 0
          ? "Local TTS worker exited unexpectedly."
          : `Local TTS worker exited with code ${code}.`;
        const startupError = buildWorkerReadyError(this.ttsWorkerStderrTail, message);
        this.clearTtsWorkerState();
        this.rejectPendingRequests(this.ttsPendingRequests, startupError);
        failStartup(startupError);
      });
    });

    await this.ttsWorkerReadyPromise;
    return child;
  }

  handleSttWorkerMessage(message) {
    if (!message || message.type !== "result" || !message.id) {
      return;
    }

    const pending = this.sttPendingRequests.get(message.id);
    if (!pending) {
      return;
    }

    this.sttPendingRequests.delete(message.id);
    if (message.error) {
      pending.reject(new Error(`Local STT failed: ${message.error}`));
      return;
    }

    pending.resolve(String(message.text || "").trim());
  }

  handleTtsWorkerMessage(message) {
    if (!message || message.type !== "result" || !message.id) {
      return;
    }

    const pending = this.ttsPendingRequests.get(message.id);
    if (!pending) {
      return;
    }

    this.ttsPendingRequests.delete(message.id);
    if (message.error) {
      pending.reject(new Error(`Local TTS failed: ${message.error}`));
      return;
    }

    pending.resolve();
  }

  rejectPendingRequests(pendingMap, error) {
    for (const [id, pending] of pendingMap.entries()) {
      pendingMap.delete(id);
      pending.reject(error);
    }
  }

  clearSttWorkerState() {
    if (this.sttWorkerLineReader) {
      this.sttWorkerLineReader.close();
      this.sttWorkerLineReader = null;
    }
    this.sttWorker = null;
    this.sttWorkerReadyPromise = null;
    this.sttWorkerReadyInfo = null;
  }

  clearTtsWorkerState() {
    if (this.ttsWorkerLineReader) {
      this.ttsWorkerLineReader.close();
      this.ttsWorkerLineReader = null;
    }
    this.ttsWorker = null;
    this.ttsWorkerReadyPromise = null;
    this.ttsWorkerReadyInfo = null;
  }

  stopSttWorker() {
    if (this.sttWorker && this.sttWorker.exitCode == null) {
      this.sttWorker.kill();
    }
    this.clearSttWorkerState();
  }

  stopTtsWorker() {
    if (this.ttsWorker && this.ttsWorker.exitCode == null) {
      this.ttsWorker.kill();
    }
    this.clearTtsWorkerState();
  }

  close() {
    this.rejectPendingRequests(this.sttPendingRequests, new Error("Speech service closed."));
    this.rejectPendingRequests(this.ttsPendingRequests, new Error("Speech service closed."));
    this.stopSttWorker();
    this.stopTtsWorker();
  }

  shouldRetryOnCpu(error) {
    if (this.sttBackend !== STT_BACKEND_FASTER_WHISPER || this.cpuFallbackActive || this.sttDevice === "cpu") {
      return false;
    }

    return /(cublas|cudnn|cuda|gpu|cannot be loaded|no gpu|driver)/i.test(error.message);
  }

  enableCpuFallback(error) {
    this.cpuFallbackActive = true;
    this.sttDevice = "cpu";
    this.sttComputeType = "int8";
    this.stopSttWorker();
    console.warn(
      `[thomas-discord] Voice STT falling back to CPU int8 after ${this.requestedSttDevice}/${this.requestedSttComputeType} failed: ${error.message}`,
    );
  }
}
