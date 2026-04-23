import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

export const OPENAI_BASE_URL = "https://api.openai.com/v1";
export const OPENAI_DEFAULT_TTS_MODEL = "gpt-4o-mini-tts";
export const OPENAI_DEFAULT_STT_MODEL = "gpt-4o-mini-transcribe";
export const OPENAI_DEFAULT_VOICE = "alloy";
export const TTS_BACKEND_PIPER = "piper";
export const TTS_BACKEND_OPENAI = "openai";
export const TTS_BACKEND_WINDOWS = "windows";
export const STT_BACKEND_FASTER_WHISPER = "faster-whisper";
export const STT_BACKEND_OPENAI = "openai";
export const STT_BACKEND_WINDOWS = "windows";
export const STT_STARTUP_TIMEOUT_MS = 10 * 60_000;
export const TTS_STARTUP_TIMEOUT_MS = 10 * 60_000;
const DEFAULT_PROJECT_ROOT = path.resolve(fileURLToPath(new URL("../../../../", import.meta.url)));

export function getProjectRoot(baseEnv = process.env) {
  return path.resolve(String(baseEnv.THOMAS_PROJECT_ROOT || DEFAULT_PROJECT_ROOT).trim() || DEFAULT_PROJECT_ROOT);
}

function collectLocalCudaLibDirs(projectRoot) {
  const cudaRoot = path.resolve(projectRoot, "runtime", ".thomas", "discord_bridge", "service_data", "cuda-libs");
  const candidates = [
    path.join(cudaRoot, "cuda12_v3"),
    cudaRoot,
  ];

  try {
    for (const entry of fs.readdirSync(cudaRoot, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        candidates.push(path.join(cudaRoot, entry.name));
      }
    }
  } catch {}

  const discovered = [];
  const seen = new Set();
  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    const normalized = process.platform === "win32" ? resolved.toLowerCase() : resolved;
    if (seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    if (fs.existsSync(path.join(resolved, "cublas64_12.dll"))) {
      discovered.push(resolved);
    }
  }
  return discovered;
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
    ...collectLocalCudaLibDirs(projectRoot),
    path.resolve(projectRoot, ".venv", "Lib", "site-packages", "torch", "lib"),
    path.resolve(projectRoot, ".venv", "Lib", "site-packages", "onnxruntime", "capi"),
  ];

  env.PATH = appendPathEntries(env.PATH, extraEntries);
  return env;
}

export function runCommand(command, args, timeoutMs, { cwd, stdinText } = {}) {
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

export function runPowerShellFile(scriptPath, args, timeoutMs) {
  return runCommand(
    resolvePowerShellCommand(process.env),
    ["-NoLogo", "-NonInteractive", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", scriptPath, ...args],
    timeoutMs,
  );
}

export function buildWorkerReadyError(stderrTail, fallbackMessage) {
  const details = stderrTail ? `: ${stderrTail}` : "";
  return new Error(`${fallbackMessage}${details}`);
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
