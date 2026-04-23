export const THOMAS_ACCESS_CAPABILITIES = Object.freeze({
  TALK: "talk",
  MEDIA: "media",
  SETTINGS: "settings",
});

export const DEFAULT_DELEGATE_CAPABILITIES = Object.freeze([
  THOMAS_ACCESS_CAPABILITIES.TALK,
  THOMAS_ACCESS_CAPABILITIES.MEDIA,
]);

export const FULL_ACCESS_CAPABILITIES = Object.freeze([
  THOMAS_ACCESS_CAPABILITIES.TALK,
  THOMAS_ACCESS_CAPABILITIES.MEDIA,
  THOMAS_ACCESS_CAPABILITIES.SETTINGS,
]);

const VALID_CAPABILITY_SET = new Set(FULL_ACCESS_CAPABILITIES);

function normalizeUserId(value) {
  const normalized = String(value || "").trim();
  return /^\d+$/.test(normalized) ? normalized : null;
}

export function normalizeCapabilities(value, fallback = DEFAULT_DELEGATE_CAPABILITIES) {
  const items = Array.isArray(value) ? value : [];
  const normalized = [...new Set(
    items
      .map((item) => String(item || "").trim().toLowerCase())
      .filter((item) => VALID_CAPABILITY_SET.has(item)),
  )];

  if (normalized.length > 0) {
    return normalized;
  }

  const fallbackItems = Array.isArray(fallback) ? fallback : [];
  return [...new Set(
    fallbackItems
      .map((item) => String(item || "").trim().toLowerCase())
      .filter((item) => VALID_CAPABILITY_SET.has(item)),
  )];
}

export function normalizeAccessGrants(value) {
  const grants = value && typeof value === "object" ? value : {};
  const normalized = {};

  for (const [userId, grant] of Object.entries(grants)) {
    const normalizedUserId = normalizeUserId(userId);
    if (!normalizedUserId || !grant || typeof grant !== "object") {
      continue;
    }

    const capabilities = normalizeCapabilities(grant.capabilities, []);
    if (capabilities.length === 0) {
      continue;
    }

    normalized[normalizedUserId] = {
      capabilities,
    };

    if (typeof grant.updatedAt === "string" && grant.updatedAt.trim()) {
      normalized[normalizedUserId].updatedAt = grant.updatedAt.trim();
    }

    const grantedBy = normalizeUserId(grant.grantedBy);
    if (grantedBy) {
      normalized[normalizedUserId].grantedBy = grantedBy;
    }
  }

  return normalized;
}

export function buildAccessGrant(capabilities, { grantedBy = null, updatedAt = null } = {}) {
  const normalizedCapabilities = normalizeCapabilities(capabilities, []);
  if (normalizedCapabilities.length === 0) {
    throw new Error("Access grant must include at least one capability.");
  }

  const grant = {
    capabilities: normalizedCapabilities,
    updatedAt: typeof updatedAt === "string" && updatedAt.trim()
      ? updatedAt.trim()
      : new Date().toISOString(),
  };

  const normalizedGrantedBy = normalizeUserId(grantedBy);
  if (normalizedGrantedBy) {
    grant.grantedBy = normalizedGrantedBy;
  }

  return grant;
}

export function getUserCapabilities(context, userId) {
  const normalizedUserId = normalizeUserId(userId);
  if (!normalizedUserId) {
    return [];
  }

  if (!context?.ownerOnlyMode) {
    return [...FULL_ACCESS_CAPABILITIES];
  }

  if (context.ownerUserIds?.has?.(normalizedUserId)) {
    return [...FULL_ACCESS_CAPABILITIES];
  }

  return normalizeCapabilities(context?.accessGrants?.[normalizedUserId]?.capabilities, []);
}

export function hasAnyCapability(context, userId, capabilities) {
  const userCapabilities = new Set(getUserCapabilities(context, userId));
  const wanted = Array.isArray(capabilities) ? capabilities : [capabilities];
  return wanted.some((capability) => userCapabilities.has(capability));
}

export function describeCapabilities(capabilities) {
  const normalized = new Set(normalizeCapabilities(capabilities, []));

  if (normalized.has(THOMAS_ACCESS_CAPABILITIES.SETTINGS)) {
    return "full access";
  }

  if (
    normalized.has(THOMAS_ACCESS_CAPABILITIES.TALK)
    && normalized.has(THOMAS_ACCESS_CAPABILITIES.MEDIA)
  ) {
    return "chat and music access";
  }

  if (normalized.has(THOMAS_ACCESS_CAPABILITIES.TALK)) {
    return "chat access";
  }

  if (normalized.has(THOMAS_ACCESS_CAPABILITIES.MEDIA)) {
    return "music access";
  }

  return "no access";
}

export function getRequiredCapabilityForNativeCommand(command) {
  switch (command?.type) {
    case "youtube_search":
    case "play":
    case "play_music":
    case "effect":
    case "join_voice_channel":
    case "leave_voice_channel":
    case "stop":
    case "pause":
    case "resume":
    case "skip":
    case "queue":
    case "volume":
    case "volume_relative":
    case "status":
      return THOMAS_ACCESS_CAPABILITIES.MEDIA;
    case "voice_profile":
    case "set_text_mentions":
    case "set_voice_wake_required":
    case "set_voice_wake_words":
    case "access_grant":
    case "access_revoke":
    case "access_list":
      return THOMAS_ACCESS_CAPABILITIES.SETTINGS;
    default:
      return null;
  }
}
