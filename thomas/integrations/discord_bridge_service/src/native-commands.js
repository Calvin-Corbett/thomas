import { resolveVoiceProfile } from "./voice-profiles.js";

const EFFECT_ALIASES = new Map([
  ["bang", "bang"],
  ["shot", "bang"],
  ["gunshot", "bang"],
  ["airhorn", "airhorn"],
  ["air horn", "airhorn"],
  ["rimshot", "rimshot"],
  ["rim shot", "rimshot"],
]);

function normalizeWhitespace(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function parseRequestedResultCount(value) {
  const normalized = normalizeWhitespace(value).toLowerCase();
  if (!normalized) {
    return null;
  }

  if (normalized === "one") {
    return 1;
  }

  const count = Number.parseInt(normalized, 10);
  return Number.isFinite(count) && count > 0 ? count : null;
}

function extractSearchOptions(value) {
  const text = normalizeWhitespace(value);
  const patterns = [
    {
      regex: /(?:,?\s*(?:and\s+)?(?:post|show|give|send|return|share)\s+(?:me\s+)?(?:just\s+)?(?:the\s+)?(?:top|first)\s+result(?:\s+only)?[.!?]*$)/i,
      limit: 1,
    },
    {
      regex: /(?:,?\s*(?:and\s+)?(?:just\s+)?(?:the\s+)?(?:top|first)\s+result(?:\s+only)?[.!?]*$)/i,
      limit: 1,
    },
    {
      regex: /(?:,?\s*(?:and\s+)?(?:post|show|give|send|return|share)\s+(?:me\s+)?(?:just\s+)?(?:the\s+)?(?:top|first)\s+(?<count>\d+|one)\s+results?(?:\s+only)?[.!?]*$)/i,
      countGroup: "count",
    },
    {
      regex: /(?:,?\s*(?:and\s+)?(?:just\s+)?(?:the\s+)?(?:top|first)\s+(?<count>\d+|one)\s+results?(?:\s+only)?[.!?]*$)/i,
      countGroup: "count",
    },
    {
      regex: /(?:,?\s*(?:and\s+)?(?:post|show|give|send|return|share)\s+(?:me\s+)?(?:just\s+)?(?<count>\d+|one)\s+results?(?:\s+only)?[.!?]*$)/i,
      countGroup: "count",
    },
    {
      regex: /(?:,?\s*(?:and\s+)?(?:just\s+)?(?<count>\d+|one)\s+results?(?:\s+only)?[.!?]*$)/i,
      countGroup: "count",
    },
  ];

  for (const pattern of patterns) {
    const match = text.match(pattern.regex);
    if (!match) {
      continue;
    }

    const query = normalizeWhitespace(text.slice(0, match.index).replace(/[.!?]+$/g, ""));
    if (!query) {
      break;
    }

    const limit = pattern.limit ?? parseRequestedResultCount(match.groups?.[pattern.countGroup]);
    return {
      query,
      limit: limit || null,
    };
  }

  return {
    query: normalizeWhitespace(text.replace(/[.!?]+$/g, "")),
    limit: null,
  };
}

function stripFillerWords(value) {
  let text = normalizeWhitespace(value);
  let changed = true;

  while (changed && text) {
    changed = false;
    const next = text
      .replace(/^(?:uh|um|hey|yo|okay|ok|please|all\s+right|alright|right|well|so|man|dude|buddy)[\s,.:;!?-]+/i, "")
      .replace(/^thomas[\s,.:;!?-]+/i, "")
      .replace(/^(?:can|could|would|will)\s+you[\s,.:;!?-]+/i, "")
      .replace(/^(?:do|give|play|show)\s+me[\s,.:;!?-]+/i, "");

    if (next !== text) {
      text = normalizeWhitespace(next);
      changed = true;
    }
  }

  return text;
}

function normalizeVoiceTarget(value) {
  return normalizeWhitespace(
    String(value || "")
      .replace(/\b(?:voice\s+)?(?:chat|channel|call|room)\b/gi, " ")
      .replace(/\bone\b$/i, " ")
      .replace(/\bnow\b$/i, " ")
      .replace(/^the\s+/i, "")
      .replace(/[.!?]+$/g, ""),
  );
}

function parseWakeWordList(value) {
  const items = normalizeWhitespace(value)
    .replace(/\band\b/gi, ",")
    .split(",")
    .map((item) => normalizeWhitespace(item))
    .filter(Boolean);

  return [...new Set(items)];
}

function parseMentionUserId(value) {
  return String(value || "").trim().match(/^<@!?(\d+)>$/)?.[1] || null;
}

function buildTargetSpec(value) {
  const text = normalizeWhitespace(value).replace(/[.!?]+$/g, "").replace(/^@+/, "");
  const targetUserId = parseMentionUserId(text);
  return targetUserId
    ? { targetUserId, targetQuery: null }
    : { targetUserId: null, targetQuery: text.replace(/['’]s$/i, "") };
}

function parseGrantedCapabilities(value) {
  const normalized = normalizeWhitespace(value).toLowerCase().replace(/[.!?]+$/g, "");
  const capabilities = new Set();
  const mentionsTalk = /\b(?:talk|chat|speak|ask)\b/.test(normalized);
  const mentionsMedia = /\b(?:music|media|soundboard|sound effects?|effects?|playback|songs?)\b/.test(normalized);
  const genericAccess = /\b(?:access|command access|use thomas|use the bot|use him|use you)\b/.test(normalized);

  if (mentionsTalk) {
    capabilities.add("talk");
  }
  if (mentionsMedia) {
    capabilities.add("media");
  }

  if (capabilities.size === 0 && genericAccess) {
    capabilities.add("talk");
    capabilities.add("media");
  }

  return [...capabilities];
}

function buildCommandMatch(text, patterns) {
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) {
      return match;
    }
  }

  return null;
}

export function normalizeEffectName(value) {
  const key = normalizeWhitespace(value).toLowerCase();
  return EFFECT_ALIASES.get(key) || null;
}

export function parseNativeCommand(text) {
  const normalized = stripFillerWords(text);
  if (!normalized) {
    return null;
  }

  const effect = normalizeEffectName(normalized.replace(/[.!?]+$/, ""));
  if (effect) {
    return { type: "effect", effect };
  }

  const soundMatch = normalized.match(/^(?:sound|soundboard|effect|play sound)\s+(?<effect>.+)$/i);
  if (soundMatch?.groups?.effect) {
    const namedEffect = normalizeEffectName(soundMatch.groups.effect);
    if (namedEffect) {
      return { type: "effect", effect: namedEffect };
    }
  }

  if (/^(?:stop|stop music|stop playback|stop everything|clear queue)$/i.test(normalized)) {
    return { type: "stop" };
  }

  if (/^(?:pause|pause music|pause playback|hold music)$/i.test(normalized)) {
    return { type: "pause" };
  }

  if (/^(?:resume|resume music|resume playback|continue|keep playing)$/i.test(normalized)) {
    return { type: "resume" };
  }

  if (/^(?:skip|skip song|skip track|next song|next track)$/i.test(normalized)) {
    return { type: "skip" };
  }

  if (/^(?:queue status|what(?:'| i)s in the queue|show the queue)$/i.test(normalized)) {
    return { type: "queue" };
  }

  if (/^(?:status|voice status|what(?:'| i)s playing|what is playing|now playing)$/i.test(normalized)) {
    return { type: "status" };
  }

  const volumeMatch = normalized.match(
    /^(?:(?:set|change)\s+)?volume(?:\s+(?:to|at))?\s+(?<value>\d{1,3})(?:\s*(?:%|percent))?$/i,
  );
  if (volumeMatch?.groups?.value) {
    return {
      type: "volume",
      volumePercent: Number.parseInt(volumeMatch.groups.value, 10),
    };
  }

  const voiceProfileMatch = normalized.match(
    /^(?:use|switch to|change to|set)\s+(?<profile>.+?)\s+voice$/i,
  ) || normalized.match(
    /^(?:voice|voice profile|voice mode)\s+(?<profile>.+)$/i,
  );
  if (voiceProfileMatch?.groups?.profile) {
    const profile = resolveVoiceProfile(voiceProfileMatch.groups.profile);
    if (profile) {
      return {
        type: "voice_profile",
        profileId: profile.id,
      };
    }
  }

  if (/^(?:reply|respond)\s+(?:only\s+)?when\s+mentioned$/i.test(normalized)
    || /^(?:mention(?:s)?\s+only|mention\s+mode\s+on)$/i.test(normalized)) {
    return {
      type: "set_text_mentions",
      requireMention: true,
    };
  }

  if (/^(?:reply|respond)\s+to\s+(?:all|everyone|everybody)$/i.test(normalized)
    || /^(?:reply|respond)\s+without\s+mention$/i.test(normalized)
    || /^(?:mention\s+mode\s+off)$/i.test(normalized)) {
    return {
      type: "set_text_mentions",
      requireMention: false,
    };
  }

  if (/^(?:require|turn on|enable)\s+(?:the\s+)?wake\s+word$/i.test(normalized)
    || /^(?:wake\s+word\s+on)$/i.test(normalized)) {
    return {
      type: "set_voice_wake_required",
      requireWakeWord: true,
    };
  }

  if (/^(?:don'?t require|disable|turn off)\s+(?:the\s+)?wake\s+word$/i.test(normalized)
    || /^(?:wake\s+word\s+off)$/i.test(normalized)) {
    return {
      type: "set_voice_wake_required",
      requireWakeWord: false,
    };
  }

  const wakeWordsMatch = normalized.match(
    /^(?:set|change)\s+(?:the\s+)?wake\s+words?\s+(?:to|as)\s+(?<words>.+)$/i,
  ) || normalized.match(
    /^(?:wake\s+words?\s+are)\s+(?<words>.+)$/i,
  );
  if (wakeWordsMatch?.groups?.words) {
    const wakeWords = parseWakeWordList(wakeWordsMatch.groups.words);
    if (wakeWords.length > 0) {
      return {
        type: "set_voice_wake_words",
        wakeWords,
      };
    }
  }

  if (/^(?:who can use thomas|who has thomas access|list thomas access|show thomas access)$/i.test(normalized)) {
    return { type: "access_list" };
  }

  const grantMatch = buildCommandMatch(normalized, [
    /^(?:allow|let|give)\s+(?<target>.+?)\s+(?<action>(?:music|chat|talk)(?:\s+and\s+(?:music|chat|talk))?\s+access)$/i,
    /^(?:allow|let|give)\s+(?<target>.+?)\s+(?<action>command access|access)$/i,
    /^(?:allow|let|give)\s+(?<target>.+?)\s+to\s+(?<action>.+)$/i,
    /^(?:allow|let|give)\s+(?<target>.+?)\s+(?<action>use\s+.+|talk\s+.+|chat\s+.+|speak\s+.+|music\s+.+|control\s+.+)$/i,
  ]);
  if (grantMatch?.groups?.target && grantMatch?.groups?.action) {
    const target = buildTargetSpec(grantMatch.groups.target);
    const capabilities = parseGrantedCapabilities(grantMatch.groups.action);
    if ((target.targetUserId || target.targetQuery) && capabilities.length > 0) {
      return {
        type: "access_grant",
        ...target,
        capabilities,
      };
    }
  }

  const revokeMatch = buildCommandMatch(normalized, [
    /^(?:remove|revoke|deny|block)\s+(?<target>.+?)(?:['’]s)?\s+(?:command\s+)?access$/i,
    /^(?:remove|revoke)\s+(?<target>.+?)\s+from\s+thomas$/i,
  ]);
  if (revokeMatch?.groups?.target) {
    const target = buildTargetSpec(revokeMatch.groups.target);
    if (target.targetUserId || target.targetQuery) {
      return {
        type: "access_revoke",
        ...target,
      };
    }
  }

  const searchMatch = buildCommandMatch(normalized, [
    /^(?:search|look up|find)\s+(?:a\s+)?youtube\s+(?:video\s+)?(?:for\s+)?(?<query>.+)$/i,
    /^(?:search|look up|find)\s+(?:video|videos)\s+(?:for\s+)?(?<query>.+)$/i,
    /^youtube\s+(?:search\s+)?(?<query>.+)$/i,
  ]);
  if (searchMatch?.groups?.query) {
    const { query, limit } = extractSearchOptions(searchMatch.groups.query);
    return {
      type: "youtube_search",
      query,
      limit,
    };
  }

  const joinVoiceMatch = buildCommandMatch(normalized, [
    /^(?:join|move(?:\s+over)?\s+to|go\s+to|switch(?:\s+over)?\s+to)\s+(?<target>.+)$/i,
  ]);
  if (joinVoiceMatch?.groups?.target) {
    const targetQuery = normalizeVoiceTarget(joinVoiceMatch.groups.target);
    if (targetQuery) {
      return {
        type: "join_voice_channel",
        targetQuery,
      };
    }
  }

  if (/^(?:leave|disconnect(?:\s+from)?|exit)\s*(?:the\s+)?(?:voice\s+)?(?:chat|channel|call|room)?$/i.test(normalized)) {
    return { type: "leave_voice_channel" };
  }

  const playMatch = buildCommandMatch(normalized, [
    /^(?:play|queue)\s+(?<query>.+)$/i,
    /^(?:put on|start)\s+(?<query>.+)$/i,
  ]);
  if (playMatch?.groups?.query) {
    return {
      type: "play",
      query: normalizeWhitespace(playMatch.groups.query.replace(/[.!?]+$/g, "")),
    };
  }

  return null;
}

export function formatDuration(seconds) {
  const totalSeconds = Number.isFinite(Number(seconds)) ? Math.max(0, Math.round(Number(seconds))) : 0;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainder = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  }

  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

export function formatTrackLine(track, index = null) {
  const prefix = index == null ? "-" : `${index}.`;
  const duration = track.durationSeconds ? ` (${formatDuration(track.durationSeconds)})` : "";
  const source = track.channel ? ` - ${track.channel}` : "";
  return `${prefix} ${track.title}${duration}${source}\n${track.webpageUrl}`;
}

export function formatYouTubeResults(query, results) {
  if (!results.length) {
    return `I couldn't find a YouTube result for "${query}".`;
  }

  if (results.length === 1) {
    return [
      `Top YouTube result for "${query}":`,
      formatTrackLine(results[0]),
    ].join("\n");
  }

  const lines = [`YouTube results for "${query}":`];
  for (let index = 0; index < results.length; index += 1) {
    lines.push(formatTrackLine(results[index], index + 1));
  }
  return lines.join("\n");
}

export function clampVolumePercent(value, fallback = 100) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.min(200, Math.max(0, parsed));
}

export function formatQueueStatus({
  currentTrack = null,
  queue = [],
  paused = false,
  volumePercent = 100,
} = {}) {
  const lines = [];

  if (currentTrack) {
    lines.push(paused ? "Paused now:" : "Now playing:");
    lines.push(formatTrackLine(currentTrack));
  } else {
    lines.push("Nothing is playing right now.");
  }

  if (queue.length > 0) {
    lines.push(`Up next (${queue.length}):`);
    for (let index = 0; index < Math.min(queue.length, 5); index += 1) {
      lines.push(formatTrackLine(queue[index], index + 1));
    }
    if (queue.length > 5) {
      lines.push(`...and ${queue.length - 5} more.`);
    }
  } else {
    lines.push("Queue: empty.");
  }

  lines.push(`Volume: ${clampVolumePercent(volumePercent)}%.`);
  return lines.join("\n");
}
