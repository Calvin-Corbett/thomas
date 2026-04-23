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

export function normalizeSearchText(value) {
  return String(value || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9\s]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const COMMON_SEARCH_STOP_WORDS = new Set([
  "a",
  "an",
  "and",
  "by",
  "for",
  "from",
  "in",
  "is",
  "it",
  "me",
  "my",
  "of",
  "official",
  "on",
  "please",
  "song",
  "the",
  "to",
  "video",
  "your",
]);

function buildWordTokens(value) {
  return normalizeSearchText(value)
    .split(" ")
    .map((token) => token.trim())
    .filter((token) => token.length > 1 && !COMMON_SEARCH_STOP_WORDS.has(token));
}

function buildCharacterBigrams(value) {
  const compact = normalizeSearchText(value).replace(/\s+/g, "");
  if (compact.length < 2) {
    return compact ? [compact] : [];
  }

  const grams = [];
  for (let index = 0; index < compact.length - 1; index += 1) {
    grams.push(compact.slice(index, index + 2));
  }
  return grams;
}

function computeDiceCoefficient(left, right) {
  const leftBigrams = buildCharacterBigrams(left);
  const rightBigrams = buildCharacterBigrams(right);
  if (!leftBigrams.length || !rightBigrams.length) {
    return 0;
  }

  const counts = new Map();
  for (const gram of leftBigrams) {
    counts.set(gram, (counts.get(gram) || 0) + 1);
  }

  let overlap = 0;
  for (const gram of rightBigrams) {
    const count = counts.get(gram) || 0;
    if (count > 0) {
      overlap += 1;
      counts.set(gram, count - 1);
    }
  }

  return (2 * overlap) / (leftBigrams.length + rightBigrams.length);
}

function computeBestTitleWindowSimilarity(queryTokens, titleTokens) {
  if (!queryTokens.length || !titleTokens.length) {
    return 0;
  }

  const windowSize = Math.min(queryTokens.length, titleTokens.length);
  const queryPhrase = queryTokens.join(" ");
  let best = 0;

  for (let index = 0; index <= titleTokens.length - windowSize; index += 1) {
    const candidatePhrase = titleTokens.slice(index, index + windowSize).join(" ");
    best = Math.max(best, computeDiceCoefficient(queryPhrase, candidatePhrase));
  }

  return best;
}

export function scoreMediaCandidate(query, entry) {
  if (!entry) {
    return Number.NEGATIVE_INFINITY;
  }

  const normalizedQuery = normalizeSearchText(query);
  const normalizedTitle = normalizeSearchText(entry.title);
  const normalizedChannel = normalizeSearchText(`${entry.channel || ""} ${entry.uploader || ""}`);
  const queryTokens = buildWordTokens(normalizedQuery);
  const titleTokens = buildWordTokens(normalizedTitle);
  const candidateTokens = new Set([
    ...titleTokens,
    ...buildWordTokens(normalizedChannel),
  ]);
  const candidateTokenList = [...candidateTokens];

  if (!normalizedQuery || !normalizedTitle) {
    return Number.NEGATIVE_INFINITY;
  }

  let overlappingTokens = 0;
  let prefixMatches = 0;
  let fuzzyMatches = 0;
  for (const token of queryTokens) {
    if (candidateTokenList.some((candidate) => candidate === token)) {
      overlappingTokens += 1;
      continue;
    }
    if (candidateTokenList.some((candidate) => candidate.startsWith(token) || token.startsWith(candidate))) {
      prefixMatches += 1;
      continue;
    }

    const bestFuzzyMatch = candidateTokenList.reduce(
      (best, candidate) => Math.max(best, computeDiceCoefficient(token, candidate)),
      0,
    );
    if (bestFuzzyMatch >= 0.45) {
      fuzzyMatches += bestFuzzyMatch;
    }
  }

  const titleDice = computeDiceCoefficient(normalizedQuery, normalizedTitle);
  const combinedDice = computeDiceCoefficient(normalizedQuery, `${normalizedTitle} ${normalizedChannel}`);
  const titleWindowDice = computeBestTitleWindowSimilarity(queryTokens, titleTokens);

  let score =
    (overlappingTokens * 6)
    + (prefixMatches * 2)
    + (fuzzyMatches * 4)
    + (titleWindowDice * 10)
    + (titleDice * 8)
    + (combinedDice * 4);

  if (normalizedTitle.includes(normalizedQuery)) {
    score += 6;
  } else if (`${normalizedTitle} ${normalizedChannel}`.includes(normalizedQuery)) {
    score += 3;
  }

  const queryWantsMix = /\b(mix|playlist|radio|top hits|songs?)\b/.test(normalizedQuery);
  if (!queryWantsMix && /\b(mix|playlist|compilation|top hits)\b/.test(normalizedTitle)) {
    score -= 4;
  }

  return score;
}

export function selectBestMediaEntry(query, entries) {
  if (!Array.isArray(entries) || entries.length === 0) {
    return null;
  }

  return [...entries]
    .filter(Boolean)
    .map((entry, index) => ({
      entry,
      index,
      score: scoreMediaCandidate(query, entry),
    }))
    .sort((left, right) => {
      if (right.score !== left.score) {
        return right.score - left.score;
      }
      return left.index - right.index;
    })[0]?.entry || null;
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

    const entries = await this.searchYouTube(input, 5);
    const entry = selectBestMediaEntry(input, entries);
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
