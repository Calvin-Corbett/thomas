import { spawn } from "node:child_process";

import { resolveCommandPath } from "./speech-service.js";

function runCommand(command, args, timeoutMs) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      windowsHide: true,
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
        reject(new Error(`yt-dlp timed out after ${timeoutMs}ms`));
        return;
      }
      if (code !== 0) {
        reject(new Error((stderr || stdout || `yt-dlp exited with code ${code}`).trim()));
        return;
      }
      resolve({
        stdout: stdout.trim(),
        stderr: stderr.trim(),
      });
    });
  });
}

export function isLikelyUrl(value) {
  return /^https?:\/\//i.test(String(value || "").trim());
}

export function isSpotifyUrl(value) {
  return /spotify\.com\//i.test(String(value || "").trim());
}

export function normalizeMediaEntry(entry) {
  if (!entry || typeof entry !== "object") {
    return null;
  }

  const webpageUrl =
    String(entry.webpage_url || entry.original_url || entry.url || "").trim();
  const title = String(entry.title || entry.fulltitle || "").trim();
  if (!title || !webpageUrl) {
    return null;
  }

  return {
    id: String(entry.id || "").trim() || null,
    title,
    webpageUrl,
    channel: String(entry.channel || entry.uploader || "").trim() || null,
    uploader: String(entry.uploader || "").trim() || null,
    durationSeconds: Number.isFinite(Number(entry.duration)) ? Math.round(Number(entry.duration)) : null,
  };
}

export function buildSearchArgs(query, limit) {
  return [
    "-m",
    "yt_dlp",
    `ytsearch${limit}:${query}`,
    "--dump-json",
    "--skip-download",
    "--flat-playlist",
    "--playlist-end",
    String(limit),
    "--no-warnings",
    "--ignore-errors",
    "--quiet",
    "--js-runtimes",
    "node",
  ];
}

export function buildMetadataArgs(url) {
  return [
    "-m",
    "yt_dlp",
    url,
    "--dump-single-json",
    "--no-playlist",
    "--no-warnings",
    "--ignore-errors",
    "--quiet",
    "--js-runtimes",
    "node",
  ];
}

export function buildStreamUrlArgs(url) {
  return [
    "-m",
    "yt_dlp",
    "-f",
    "bestaudio[acodec!=none]/bestaudio/best",
    "-g",
    "--no-playlist",
    "--no-warnings",
    "--quiet",
    "--js-runtimes",
    "node",
    url,
  ];
}

export class MediaService {
  constructor({
    pythonBin = "python",
    timeoutMs = 45_000,
  } = {}) {
    this.pythonBin = resolveCommandPath(pythonBin);
    this.timeoutMs = timeoutMs;
  }

  async searchYouTube(query, limit = 3) {
    const { stdout } = await runCommand(this.pythonBin, buildSearchArgs(query, limit), this.timeoutMs);
    return stdout
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        try {
          return normalizeMediaEntry(JSON.parse(line));
        } catch {
          return null;
        }
      })
      .filter(Boolean);
  }

  async fetchMetadata(url) {
    const { stdout } = await runCommand(this.pythonBin, buildMetadataArgs(url), this.timeoutMs);
    return normalizeMediaEntry(JSON.parse(stdout));
  }

  async resolveTrack(input) {
    if (isSpotifyUrl(input)) {
      throw new Error("Spotify links are not supported directly yet. Say the song name or use a YouTube link.");
    }

    if (isLikelyUrl(input)) {
      const entry = await this.fetchMetadata(input);
      if (!entry) {
        throw new Error("I couldn't read that media link.");
      }
      return entry;
    }

    const [entry] = await this.searchYouTube(input, 1);
    if (!entry) {
      throw new Error(`I couldn't find a playable YouTube result for "${input}".`);
    }
    return entry;
  }

  async getStreamUrl(url) {
    const { stdout } = await runCommand(this.pythonBin, buildStreamUrlArgs(url), this.timeoutMs);
    const lines = stdout
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    const streamUrl = [...lines].reverse().find((line) => /^https?:\/\//i.test(line));
    if (!streamUrl) {
      throw new Error("yt-dlp did not return a playable audio stream.");
    }
    return streamUrl;
  }

  async resolvePlayback(input) {
    const entry = await this.resolveTrack(input);
    const streamUrl = await this.getStreamUrl(entry.webpageUrl);
    return {
      ...entry,
      streamUrl,
    };
  }
}
