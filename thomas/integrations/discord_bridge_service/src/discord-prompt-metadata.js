function normalizeString(value) {
  const normalized = String(value || "").trim();
  return normalized || null;
}

function normalizeCapabilityList(value) {
  if (!Array.isArray(value)) {
    return [];
  }

  return [...new Set(
    value
      .map((item) => normalizeString(item))
      .filter(Boolean),
  )];
}

export function buildDiscordPromptMetadata({
  userId,
  displayName,
  guildId = null,
  channelId = null,
  scopeKey,
  grantedCapabilities = [],
  isOwner = false,
  ownerAuthorizedForSettingsActions = false,
  ownerOnlyMode = false,
  source = "discord-bridge",
  surface = "discord",
  client = "discord_bot",
  slashCommand = null,
  requestKind = "message",
} = {}) {
  return {
    source,
    scope_key: normalizeString(scopeKey),
    discord: {
      user_id: normalizeString(userId),
      display_name: normalizeString(displayName),
      guild_id: normalizeString(guildId),
      channel_id: normalizeString(channelId),
      owner: Boolean(isOwner),
      owner_only_mode: Boolean(ownerOnlyMode),
      granted_capabilities: normalizeCapabilityList(grantedCapabilities),
      surface: normalizeString(surface),
      client: normalizeString(client),
      slash_command: normalizeString(slashCommand),
      request_kind: normalizeString(requestKind),
      owner_authorized_for_settings_actions: Boolean(ownerAuthorizedForSettingsActions),
    },
  };
}
