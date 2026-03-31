import fsPromises from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";

import ffmpegPath from "ffmpeg-static";

const EFFECT_SPECS = {
  bang: {
    fileName: "bang.wav",
    args: [
      "-y",
      "-f",
      "lavfi",
      "-i",
      "sine=frequency=58:duration=0.22",
      "-f",
      "lavfi",
      "-i",
      "anoisesrc=color=white:duration=0.12",
      "-filter_complex",
      "[0:a]volume=1.8,afade=t=out:st=0.14:d=0.08[thump];[1:a]highpass=f=900,lowpass=f=4500,volume=0.55,afade=t=out:st=0.05:d=0.07[blast];[thump][blast]amix=inputs=2:weights='1 0.8',alimiter=limit=0.95[a]",
      "-map",
      "[a]",
      "-ar",
      "48000",
      "-ac",
      "2",
    ],
  },
  airhorn: {
    fileName: "airhorn.wav",
    args: [
      "-y",
      "-f",
      "lavfi",
      "-i",
      "sine=frequency=440:duration=1.1",
      "-f",
      "lavfi",
      "-i",
      "sine=frequency=554:duration=1.1",
      "-filter_complex",
      "[0:a]volume=0.7[a0];[1:a]volume=0.7[a1];[a0][a1]amix=inputs=2,volume=2.0,afade=t=in:st=0:d=0.05,afade=t=out:st=0.9:d=0.2,alimiter=limit=0.95[a]",
      "-map",
      "[a]",
      "-ar",
      "48000",
      "-ac",
      "2",
    ],
  },
  rimshot: {
    fileName: "rimshot.wav",
    args: [
      "-y",
      "-f",
      "lavfi",
      "-i",
      "anoisesrc=color=white:duration=0.1",
      "-f",
      "lavfi",
      "-i",
      "sine=frequency=190:duration=0.14",
      "-filter_complex",
      "[0:a]highpass=f=1800,lowpass=f=7000,volume=0.45,afade=t=out:st=0.03:d=0.07[stick];[1:a]volume=1.3,afade=t=out:st=0.08:d=0.06[body];[stick][body]amix=inputs=2:weights='1 0.9',alimiter=limit=0.95[a]",
      "-map",
      "[a]",
      "-ar",
      "48000",
      "-ac",
      "2",
    ],
  },
};

function runFfmpeg(args, timeoutMs) {
  return new Promise((resolve, reject) => {
    const child = spawn(ffmpegPath, args, {
      windowsHide: true,
    });

    let stderr = "";
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, timeoutMs);

    child.stderr.setEncoding("utf8");
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
        reject(new Error("ffmpeg timed out while generating soundboard assets"));
        return;
      }
      if (code !== 0) {
        reject(new Error((stderr || `ffmpeg exited with code ${code}`).trim()));
        return;
      }
      resolve();
    });
  });
}

export function listSoundEffects() {
  return Object.keys(EFFECT_SPECS);
}

export function buildSoundEffectPath(dataDir, effectName) {
  const spec = EFFECT_SPECS[effectName];
  if (!spec) {
    return null;
  }
  return path.join(dataDir, "soundboard", spec.fileName);
}

export async function ensureDefaultSoundEffects(dataDir, timeoutMs = 30_000) {
  const soundboardDir = path.join(dataDir, "soundboard");
  await fsPromises.mkdir(soundboardDir, { recursive: true });

  for (const [effectName, spec] of Object.entries(EFFECT_SPECS)) {
    const outputPath = path.join(soundboardDir, spec.fileName);
    try {
      await fsPromises.access(outputPath);
    } catch {
      await runFfmpeg([...spec.args, outputPath], timeoutMs);
      console.log(`[thomas-discord] Generated soundboard effect: ${effectName}`);
    }
  }
}
