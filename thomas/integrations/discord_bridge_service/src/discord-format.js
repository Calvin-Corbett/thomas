const INTERNAL_REPLY_HINTS = [
  /\bi['’]?m treating this as\b/i,
  /\bi am treating this as\b/i,
  /\bi don['’]?t see any recorded tool calls\b/i,
  /\bthe repo guardrails are loaded\b/i,
  /\bthe router\b/i,
  /\bstartup checks?\b/i,
  /\bpolicy reads?\b/i,
  /\bworktree is dirty\b/i,
  /\bno-edit lane\b/i,
  /\brepo-native\b/i,
  /\brepo note:\b/i,
  /\bblockers i verified:\b/i,
  /\bdiscord credentials\b/i,
  /\brecorded tool calls\b/i,
  /\bconversation context\b/i,
  /\bno tools were executed\b/i,
  /\bmissing token or webhook\b/i,
  /\bopening in existing browser session\b/i,
  /\bbrowser fallback\b/i,
  /\bwebhook or bot token\b/i,
  /\bpermission to use a specific logged-in browser\/session path\b/i,
  /\bpreflight_status:\s*blocked\b/i,
  /\bpython\s+scripts\/agent_startup_router\.py\b/i,
  /\bpython\s+-m\s+thomas\b/i,
];

const EXTRACTION_PATTERNS = [
  /\bReply with:\s*([\s\S]+?)(?=\b(?:Repo note:|Blockers I verified:|If you want)\b|$)/i,
  /\bBest reply to send:\s*([\s\S]+?)(?=\b(?:If you want)\b|$)/i,
  /\bIf you want a ready-to-paste version[^:]*:\s*([\s\S]+?)(?=\b(?:If you want)\b|$)/i,
  /\bThe likely reply\b[^:]*:\s*([\s\S]+?)(?=\bIf you want\b|$)/i,
];

const TRAILING_META_MARKERS = [
  /\bRepo note:/i,
  /\bBlockers I verified:/i,
  /\bIf you want\b/i,
];

const CLARIFICATION_FALLBACK_HINTS = [
  /\bsay that again\b/i,
  /\bone short sentence\b/i,
  /\bi(?:'| a)m?ll answer directly\b/i,
  /\brepeat that\b/i,
];

export const DISCORD_REPLY_GUARDRAIL = [
  "Return only the final user-facing reply for Discord.",
  "Do not mention internal startup checks, routing, repo state, policy reads, tools, browser sessions, credentials, blockers, or what you are about to do.",
  "Never include analysis, scratch work, or instructions to yourself.",
  "Keep the answer as normal chat text unless the user explicitly asks for code or a list.",
].join(" ");

export function cleanDiscordPrompt(content, clientUserId) {
  const raw = String(content || "");
  if (!clientUserId) {
    return raw.trim();
  }

  const mentionPattern = new RegExp(`<@!?${clientUserId}>`, "g");
  return raw.replace(mentionPattern, "").trim();
}

export function splitForDiscord(text, maxLength) {
  const source = String(text || "").trim();
  if (!source) {
    return ["Thomas did not return any text."];
  }

  if (source.length <= maxLength) {
    return [source];
  }

  const chunks = [];
  let remaining = source;

  while (remaining.length > maxLength) {
    let cut = remaining.lastIndexOf("\n\n", maxLength);
    if (cut < Math.floor(maxLength * 0.5)) {
      cut = remaining.lastIndexOf("\n", maxLength);
    }
    if (cut < Math.floor(maxLength * 0.5)) {
      cut = remaining.lastIndexOf(" ", maxLength);
    }
    if (cut < 1) {
      cut = maxLength;
    }

    chunks.push(remaining.slice(0, cut).trim());
    remaining = remaining.slice(cut).trim();
  }

  if (remaining) {
    chunks.push(remaining);
  }

  return chunks.filter(Boolean);
}

export function describeScope(message) {
  if (!message.guild) {
    return `DM with ${message.author.username}`;
  }

  const channelName = "name" in message.channel && message.channel.name ? `#${message.channel.name}` : "channel";
  return `${message.guild.name} ${channelName}`;
}

function stripReplyFormatting(text) {
  return String(text || "")
    .replace(/\r/g, "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    .replace(/https?:\/\/\S+/gi, "")
    .trim();
}

function cleanupReplyText(text) {
  return String(text || "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function trimTrailingMeta(text) {
  let cut = text.length;
  for (const marker of TRAILING_META_MARKERS) {
    const match = marker.exec(text);
    if (match && match.index < cut) {
      cut = match.index;
    }
  }

  return cleanupReplyText(text.slice(0, cut));
}

function isInternalParagraph(paragraph) {
  return INTERNAL_REPLY_HINTS.some((pattern) => pattern.test(paragraph));
}

function looksInternal(text) {
  return INTERNAL_REPLY_HINTS.some((pattern) => pattern.test(text));
}

export function replyLooksInternal(text) {
  return looksInternal(cleanupReplyText(stripReplyFormatting(text)));
}

export function replyLooksClarificationFallback(text) {
  const source = cleanupReplyText(stripReplyFormatting(text));
  if (!source) {
    return false;
  }

  const matchedCount = CLARIFICATION_FALLBACK_HINTS.filter((pattern) => pattern.test(source)).length;
  return matchedCount >= 2 || /^say that again\b/i.test(source);
}

function extractUserFacingReply(text) {
  for (const pattern of EXTRACTION_PATTERNS) {
    const match = text.match(pattern);
    if (!match?.[1]) {
      continue;
    }

    const extracted = trimTrailingMeta(match[1]);
    if (extracted) {
      return extracted;
    }
  }

  return "";
}

export function sanitizeDiscordReply(text) {
  const source = cleanupReplyText(stripReplyFormatting(text));
  if (!source) {
    return "Thomas did not return any text.";
  }

  const extracted = extractUserFacingReply(source);
  if (extracted) {
    return extracted;
  }

  const paragraphs = source
    .split(/\n{2,}/)
    .map((paragraph) => cleanupReplyText(paragraph))
    .filter(Boolean);

  const safeParagraphs = paragraphs.filter((paragraph) => !isInternalParagraph(paragraph));
  const safeReply = cleanupReplyText(safeParagraphs.join("\n\n"));
  if (safeReply) {
    return safeReply;
  }

  if (looksInternal(source)) {
    return "Say that again in one short sentence and I'll answer directly.";
  }

  return source;
}
