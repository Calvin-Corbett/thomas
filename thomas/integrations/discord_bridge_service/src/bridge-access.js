import {
  THOMAS_ACCESS_CAPABILITIES,
  buildAccessGrant,
  describeCapabilities,
  getUserCapabilities as getGrantedUserCapabilities,
  hasAnyCapability,
} from "./discord-access.js";

function normalizeMemberLookup(value) {
  return String(value || "").trim().replace(/^@+/, "").toLowerCase();
}

export function createAccessController({ config, settingsStore }) {
  function isOwnerUser(userId) {
    if (config.ownerUserIds.size === 0) {
      return true;
    }
    return config.ownerUserIds.has(String(userId || "").trim());
  }

  function getAccessContext() {
    return {
      ownerOnlyMode: config.ownerOnlyMode,
      ownerUserIds: config.ownerUserIds,
      accessGrants: settingsStore.get("accessGrants") || {},
    };
  }

  function getUserCapabilities(userId) {
    return getGrantedUserCapabilities(getAccessContext(), userId);
  }

  function canUserUseCapability(userId, capability) {
    return hasAnyCapability(getAccessContext(), userId, [capability]);
  }

  function canUserTalk(userId) {
    return canUserUseCapability(userId, THOMAS_ACCESS_CAPABILITIES.TALK);
  }

  function canUserUseMedia(userId) {
    return canUserUseCapability(userId, THOMAS_ACCESS_CAPABILITIES.MEDIA);
  }

  function canUserManageSettings(userId) {
    return canUserUseCapability(userId, THOMAS_ACCESS_CAPABILITIES.SETTINGS);
  }

  function isGuildAllowed(guildId) {
    return config.allowedGuildIds.size === 0 || config.allowedGuildIds.has(guildId);
  }

  async function resolveAccessTargetMember(guild, command) {
    if (!guild) {
      throw new Error("Access changes only work in a server.");
    }

    if (command.targetUserId) {
      const member = await guild.members.fetch(command.targetUserId).catch(() => null);
      if (!member) {
        throw new Error("I couldn't find that member in this server.");
      }
      if (member.user.bot) {
        throw new Error("Access grants are only for human members.");
      }
      return member;
    }

    const query = normalizeMemberLookup(command.targetQuery);
    if (!query) {
      throw new Error("Tell me which member to update.");
    }

    const members = await guild.members.fetch();
    const candidates = [...members.values()].filter((member) => !member.user.bot);
    const exactMatches = candidates.filter((member) =>
      [
        member.displayName,
        member.nickname,
        member.user.globalName,
        member.user.username,
      ]
        .map(normalizeMemberLookup)
        .some((name) => name === query),
    );

    if (exactMatches.length === 1) {
      return exactMatches[0];
    }

    if (exactMatches.length > 1) {
      throw new Error(`More than one member matched "${command.targetQuery}". Mention them instead.`);
    }

    const partialMatches = candidates.filter((member) =>
      [
        member.displayName,
        member.nickname,
        member.user.globalName,
        member.user.username,
      ]
        .map(normalizeMemberLookup)
        .some((name) => name.includes(query)),
    );

    if (partialMatches.length === 1) {
      return partialMatches[0];
    }

    if (partialMatches.length > 1) {
      throw new Error(`More than one member matched "${command.targetQuery}". Mention them instead.`);
    }

    throw new Error(`I couldn't find "${command.targetQuery}" in this server.`);
  }

  async function grantMemberAccess(targetMember, capabilities, grantedByUserId) {
    if (isOwnerUser(targetMember.id)) {
      return {
        changed: false,
        owner: true,
        grant: buildAccessGrant(
          [
            THOMAS_ACCESS_CAPABILITIES.TALK,
            THOMAS_ACCESS_CAPABILITIES.MEDIA,
            THOMAS_ACCESS_CAPABILITIES.SETTINGS,
          ],
          { grantedBy: grantedByUserId },
        ),
      };
    }

    const currentGrants = settingsStore.get("accessGrants") || {};
    const nextGrant = buildAccessGrant(capabilities, { grantedBy: grantedByUserId });
    const previousGrant = currentGrants[targetMember.id] || null;
    const changed = JSON.stringify(previousGrant?.capabilities || []) !== JSON.stringify(nextGrant.capabilities);

    await settingsStore.update({
      accessGrants: {
        ...currentGrants,
        [targetMember.id]: nextGrant,
      },
    });

    return {
      changed,
      owner: false,
      grant: nextGrant,
    };
  }

  async function revokeMemberAccess(targetMember) {
    if (isOwnerUser(targetMember.id)) {
      return {
        changed: false,
        owner: true,
      };
    }

    const currentGrants = settingsStore.get("accessGrants") || {};
    if (!currentGrants[targetMember.id]) {
      return {
        changed: false,
        owner: false,
      };
    }

    const nextGrants = { ...currentGrants };
    delete nextGrants[targetMember.id];
    await settingsStore.update({ accessGrants: nextGrants });
    return {
      changed: true,
      owner: false,
    };
  }

  async function formatDelegatedAccessList(guild) {
    const accessGrants = settingsStore.get("accessGrants") || {};
    const userIds = Object.keys(accessGrants);
    if (userIds.length === 0) {
      return "Delegated Thomas access: none.";
    }

    const lines = ["Delegated Thomas access:"];
    for (const userId of userIds.sort()) {
      const member = guild ? await guild.members.fetch(userId).catch(() => null) : null;
      const label = member?.displayName || member?.user?.globalName || member?.user?.username || `User ${userId}`;
      lines.push(`- ${label}: ${describeCapabilities(accessGrants[userId].capabilities)}`);
    }
    return lines.join("\n");
  }

  function buildAccessDeniedMessage(requiredCapability, userId) {
    if (requiredCapability === THOMAS_ACCESS_CAPABILITIES.SETTINGS) {
      return "Only War Machine Pro can change Thomas settings or access.";
    }

    const capabilities = new Set(getUserCapabilities(userId));
    if (requiredCapability === THOMAS_ACCESS_CAPABILITIES.MEDIA && capabilities.has(THOMAS_ACCESS_CAPABILITIES.TALK)) {
      return "You can talk to Thomas, but you do not have music control.";
    }

    if (requiredCapability === THOMAS_ACCESS_CAPABILITIES.TALK && capabilities.has(THOMAS_ACCESS_CAPABILITIES.MEDIA)) {
      return "You can use Thomas for music, but you do not have chat access.";
    }

    return "You do not have access to that Thomas command.";
  }

  return {
    isOwnerUser,
    getAccessContext,
    getUserCapabilities,
    canUserUseCapability,
    canUserTalk,
    canUserUseMedia,
    canUserManageSettings,
    isGuildAllowed,
    resolveAccessTargetMember,
    grantMemberAccess,
    revokeMemberAccess,
    formatDelegatedAccessList,
    buildAccessDeniedMessage,
  };
}
