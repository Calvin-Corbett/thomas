import { randomUUID } from "node:crypto";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

function runPowerShellFile(scriptPath, args, timeoutMs) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      "powershell.exe",
      ["-NoLogo", "-NonInteractive", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", scriptPath, ...args],
      {
        windowsHide: true,
      },
    );

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
        reject(new Error(`PowerShell timed out while running ${path.basename(scriptPath)}`));
        return;
      }
      if (code !== 0) {
        reject(new Error((stderr || stdout || `PowerShell exited with code ${code}`).trim()));
        return;
      }
      resolve({ stdout: stdout.trim(), stderr: stderr.trim() });
    });
  });
}

export class WindowsSpeechService {
  constructor({ voiceName = null, synthTimeoutMs = 45000, transcribeTimeoutMs = 45000 } = {}) {
    this.voiceName = voiceName;
    this.synthTimeoutMs = synthTimeoutMs;
    this.transcribeTimeoutMs = transcribeTimeoutMs;
    this.synthScript = fileURLToPath(new URL("../scripts/synthesize-wav.ps1", import.meta.url));
    this.transcribeScript = fileURLToPath(new URL("../scripts/transcribe-wav.ps1", import.meta.url));
  }

  createTempWavePath(prefix) {
    return path.join(os.tmpdir(), `${prefix}-${randomUUID()}.wav`);
  }

  async synthesizeToWav(text) {
    const outputPath = this.createTempWavePath("thomas-voice-out");
    const args = ["-Text", String(text || ""), "-OutputPath", outputPath];
    if (this.voiceName) {
      args.push("-VoiceName", this.voiceName);
    }

    await runPowerShellFile(this.synthScript, args, this.synthTimeoutMs);
    return outputPath;
  }

  async transcribeWav(inputPath) {
    const result = await runPowerShellFile(this.transcribeScript, ["-InputPath", inputPath], this.transcribeTimeoutMs);
    return result.stdout.trim();
  }
}
