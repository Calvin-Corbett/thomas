function normalizeWhitespace(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function normalizeComparableText(value) {
  return normalizeWhitespace(String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " "));
}

function tokenizeTranscript(value) {
  return normalizeComparableText(value)
    .split(" ")
    .map((token) => token.trim())
    .filter(Boolean);
}

const GREETING_WAKE_WORDS = new Set(["hey", "yo", "okay", "ok"]);
const THOMAS_ALIAS_TOKENS = new Set([
  "tomas",
  "thomis",
  "davis",
]);

function spellShortAcronyms(value) {
  return String(value || "").replace(/\b([A-Z]{2,5})(?:'s)?\b/g, (match) => {
    const suffix = match.endsWith("'s") ? "'s" : "";
    const letters = suffix ? match.slice(0, -2) : match;
    return `${letters.split("").join(" ")}${suffix ? "s" : ""}`;
  });
}

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function trimWakeRemainder(value) {
  return normalizeWhitespace(String(value || "").replace(/^[\s,.:;!?-]+/, ""));
}

function getNormalizedWakeWords(wakeWords) {
  return [...new Set(
    (Array.isArray(wakeWords) ? wakeWords : [])
      .map((rawWakeWord) => normalizeWhitespace(rawWakeWord).toLowerCase())
      .filter(Boolean),
  )].sort((left, right) => right.length - left.length);
}

function matchWakeWordAnywhere(normalized, wakeWord) {
  const wakeWordPattern = wakeWord
    .split(/\s+/)
    .map((part) => escapeRegExp(part))
    .join("[\\s,.:;!?-]+");
  const match = normalized.match(new RegExp(`(^|[\\s,.:;!?-])(?<wake>${wakeWordPattern})(?=$|[\\s,.:;!?-])`, "i"));
  if (!match?.groups?.wake || match.index == null) {
    return null;
  }

  const wakeIndex = match.index + match[1].length;
  const before = trimWakeRemainder(normalized.slice(0, wakeIndex));
  const after = trimWakeRemainder(normalized.slice(wakeIndex + match.groups.wake.length));
  return {
    before,
    after,
  };
}

function supportsThomasWakeAliases(wakeWords) {
  return getNormalizedWakeWords(wakeWords).some((wakeWord) =>
    wakeWord.includes("thomas"),
  );
}

function matchGreetingWakeAlias(normalized, wakeWords) {
  if (!supportsThomasWakeAliases(wakeWords)) {
    return null;
  }

  const tokens = tokenizeTranscript(normalized);
  if (tokens.length < 2 || !GREETING_WAKE_WORDS.has(tokens[0]) || !THOMAS_ALIAS_TOKENS.has(tokens[1])) {
    return null;
  }

  const remainder = normalizeWhitespace(tokens.slice(2).join(" "));
  return remainder || "hello";
}

export function extractWakePhrase(transcript, { wakeWords = [], requireWakeWord = true } = {}) {
  const normalized = normalizeWhitespace(transcript);
  if (!normalized) {
    return null;
  }

  if (!requireWakeWord) {
    return normalized;
  }

  const greetingAliasMatch = matchGreetingWakeAlias(normalized, wakeWords);
  if (greetingAliasMatch) {
    return greetingAliasMatch;
  }

  const lower = normalized.toLowerCase();
  for (const wakeWord of getNormalizedWakeWords(wakeWords)) {
    if (lower === wakeWord) {
      return "hello";
    }

    if (lower.startsWith(wakeWord)) {
      const remainder = trimWakeRemainder(normalized.slice(wakeWord.length));
      return remainder || "hello";
    }

    const match = matchWakeWordAnywhere(normalized, wakeWord);
    if (!match) {
      continue;
    }

    return trimWakeRemainder(`${match.before} ${match.after}`) || "hello";
  }

  return null;
}

export function isWakeGreetingPhrase(value) {
  return normalizeWhitespace(value).toLowerCase() === "hello";
}

export function formatSpeechText(text, maxLength) {
  let spoken = String(text || "");

  spoken = spoken
    .replace(/```[\s\S]*?```/g, " code block omitted ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/[_*~>#]/g, " ");

  spoken = normalizeWhitespace(spoken);
  if (!spoken) {
    return "";
  }

  if (spoken.length <= maxLength) {
    return spoken;
  }

  let cut = spoken.lastIndexOf(". ", maxLength);
  if (cut < Math.floor(maxLength * 0.6)) {
    cut = spoken.lastIndexOf(" ", maxLength);
  }
  if (cut < 1) {
    cut = maxLength;
  }

  return `${spoken.slice(0, cut).trim()}...`;
}

export function normalizeTtsText(text) {
  let spoken = String(text || "");

  spoken = spellShortAcronyms(spoken);
  spoken = spoken
    .replace(/&/g, " and ")
    .replace(/@/g, " at ")
    .replace(/\b(\d+)\s*%/g, "$1 percent")
    .replace(/\+/g, " plus ")
    .replace(/\//g, " slash ")
    .replace(/#/g, " number ")
    .replace(/[:;]+/g, ". ")
    .replace(/[()[\]{}]/g, " ")
    .replace(/\.{2,}/g, ". ")
    .replace(/[!?]{2,}/g, ". ")
    .replace(/\s*-\s*/g, " ")
    .replace(/\bvs\.\b/gi, "versus");

  spoken = normalizeWhitespace(spoken);
  spoken = spoken
    .replace(/\s+([,.!?])/g, "$1")
    .replace(/([,.!?])(?!\s|$)/g, "$1 ")
    .replace(/\s+/g, " ");

  return spoken.trim();
}

export function looksLikeSpeechEcho(transcript, recentSpeechText) {
  const heard = normalizeComparableText(transcript);
  const spoken = normalizeComparableText(recentSpeechText);
  if (!heard || !spoken) {
    return false;
  }

  if (heard === spoken) {
    return true;
  }

  if (heard.length >= 12 && spoken.length >= 12) {
    if (heard.includes(spoken) || spoken.includes(heard)) {
      return true;
    }
  }

  const heardTokens = heard.split(" ").filter(Boolean);
  const spokenTokens = spoken.split(" ").filter(Boolean);
  if (heardTokens.length < 3 || spokenTokens.length < 3) {
    return false;
  }

  const spokenTokenSet = new Set(spokenTokens);
  const sharedCount = heardTokens.filter((token) => spokenTokenSet.has(token)).length;
  const overlap = sharedCount / Math.max(Math.min(heardTokens.length, spokenTokens.length), 1);
  return overlap >= 0.85;
}

export function shouldCooldownAfterMissedWake(
  transcript,
  {
    wakeWords = [],
    requireWakeWord = true,
    minWordCount = 10,
  } = {},
) {
  if (!requireWakeWord) {
    return false;
  }

  const normalized = normalizeWhitespace(transcript);
  if (!normalized) {
    return false;
  }

  const words = tokenizeTranscript(normalized);
  if (words.length < minWordCount) {
    return false;
  }

  const lower = normalized.toLowerCase();
  for (const rawWakeWord of wakeWords) {
    const wakeWord = normalizeWhitespace(rawWakeWord).toLowerCase();
    if (wakeWord && lower.includes(wakeWord)) {
      return false;
    }
  }

  return true;
}
