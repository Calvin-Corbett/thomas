import { THOMAS_ACCESS_CAPABILITIES } from "./discord-access.js";
import {
  describeScope,
  replyLooksInternal,
  sanitizeDiscordReply,
  splitForDiscord,
} from "./discord-format.js";
import { buildDiscordPromptMetadata } from "./discord-prompt-metadata.js";
import { isTextAddressedToBot } from "./discord-routing.js";

export function createBridgeHelpers({
  client,
  config,
  settingsStore,
  slashCommands,
  thomas,
  sessionStore,
  voiceManager,
  isGuildAllowed,
  getUserCapabilities,
  isOwnerUser,
  canUserManageSettings,
}) {
  function shouldProcessMessage(message) {
    if (message.author.bot) {
      return false;
    }

    if (!message.guild) {
      return true;
    }

    if (!isGuildAllowed(message.guild.id)) {
      return false;
    }

    if (!settingsStore.get("requireMention")) {
      return true;
    }

    if (message.mentions.has(client.user.id)) {
      return true;
    }

    return isTextAddressedToBot(message.content, {
      botNames: [client.user?.username, client.user?.globalName, "Thomas"],
      configuredWakeWords: settingsStore.get("voiceWakeWords"),
    });
  }

  function buildPrompt({ message, cleanedContent }) {
    const attachmentLines = [...message.attachments.values()].map(
      (attachment) => `- ${attachment.name || "attachment"}: ${attachment.url}`,
    );
    const sender = message.member?.displayName || message.author.globalName || message.author.username;
    const sections = [
      `Reply naturally to ${sender} in chat.`,
      `Context: ${describeScope(message)}.`,
      `User said: ${cleanedContent || "(no text)"}`,
    ];
    if (message.reference?.messageId) {
      sections.push("This message is a reply to an earlier chat message.");
    }
    if (attachmentLines.length > 0) {
      sections.push(`Attachments: ${attachmentLines.join(" ")}`);
    }
    return sections.join(" ");
  }

  function getDisplayNameForUser(user, member) {
    return member?.displayName || user?.globalName || user?.username || null;
  }

  function buildDiscordPromptMetadataForMessage(message, scopeKey) {
    const grantedCapabilities = getUserCapabilities(message.author.id);
    return buildDiscordPromptMetadata({
      userId: message.author.id,
      displayName: getDisplayNameForUser(message.author, message.member),
      guildId: message.guild?.id || null,
      channelId: message.channel?.id || null,
      scopeKey,
      grantedCapabilities,
      isOwner: isOwnerUser(message.author.id),
      ownerAuthorizedForSettingsActions: canUserManageSettings(message.author.id),
      ownerOnlyMode: config.ownerOnlyMode,
    });
  }

  function buildDiscordPromptMetadataForInteraction(interaction, scopeKey, slashCommand) {
    const grantedCapabilities = getUserCapabilities(interaction.user.id);
    return buildDiscordPromptMetadata({
      userId: interaction.user.id,
      displayName: getDisplayNameForUser(interaction.user, interaction.member),
      guildId: interaction.guildId || null,
      channelId: interaction.channelId || null,
      scopeKey,
      grantedCapabilities,
      isOwner: isOwnerUser(interaction.user.id),
      ownerAuthorizedForSettingsActions: canUserManageSettings(interaction.user.id),
      ownerOnlyMode: config.ownerOnlyMode,
      slashCommand,
      requestKind: "slash_command",
    });
  }

  function buildRetryPrompt(prompt) {
    return ["Reply again as normal chat to the user.", prompt].join(" ");
  }

  function extractLiteralReplyRequest(text) {
    const match = String(text || "").match(/^\s*reply with exactly:\s*([\s\S]+?)\s*$/i);
    return match?.[1]?.trim() || null;
  }

  async function syncCommands() {
    if (!client.application) {
      return;
    }
    if (config.guildId) {
      const guild = await client.guilds.fetch(config.guildId);
      await guild.commands.set(slashCommands);
      console.log(`[thomas-discord] Synced slash commands to guild ${guild.id}`);
      return;
    }
    await client.application.commands.set(slashCommands);
    console.log("[thomas-discord] Synced global slash commands");
  }

  async function sendLongReply(target, text, options = {}) {
    const parts = splitForDiscord(text, config.maxReplyChars);
    for (let index = 0; index < parts.length; index += 1) {
      const part = parts[index];
      if (index === 0 && options.replyToMessage && typeof options.replyToMessage.reply === "function") {
        await options.replyToMessage.reply({
          content: part,
          allowedMentions: { repliedUser: false },
        });
        continue;
      }
      await target.send(part);
    }
  }

  async function ensureVoiceSessionForMember(member, textChannelId) {
    const existing = voiceManager.getSession(member.guild.id);
    if (existing) {
      await voiceManager.updateLinkedTextChannel(member.guild.id, textChannelId);
      return existing;
    }
    if (!member.voice?.channel) {
      throw new Error("Join a voice channel first so Thomas knows where to play audio.");
    }
    return voiceManager.joinChannel(member.voice.channel, {
      textChannelId,
      announce: false,
    });
  }

  async function handleDiscordPrompt({ scopeKey, sessionId, prompt, replyTarget, replyToMessage }) {
    const metadata = buildDiscordPromptMetadataForMessage(replyToMessage, scopeKey);
    let result = await thomas.sendMessage({ sessionId, prompt, metadata });
    if (replyLooksInternal(result.text)) {
      const retrySessionId = await sessionStore.reset(scopeKey);
      result = await thomas.sendMessage({
        sessionId: retrySessionId,
        prompt: buildRetryPrompt(prompt),
        metadata: { ...metadata, retried_after_internal_reply: true },
      });
      if (replyLooksInternal(result.text)) {
        await sessionStore.reset(scopeKey);
      }
    }
    const replyText = sanitizeDiscordReply(result.text);
    await sendLongReply(replyTarget, replyText, { replyToMessage });
  }

  function getInteractionRequiredCapabilities(interaction) {
    if (interaction.commandName === "reset" || interaction.commandName === "status") {
      return [THOMAS_ACCESS_CAPABILITIES.SETTINGS];
    }
    if (interaction.commandName === "thomas") {
      return [THOMAS_ACCESS_CAPABILITIES.TALK];
    }
    if (interaction.commandName !== "voice") {
      return [];
    }

    switch (interaction.options.getSubcommand()) {
      case "join":
      case "leave":
      case "status":
        return [THOMAS_ACCESS_CAPABILITIES.TALK, THOMAS_ACCESS_CAPABILITIES.MEDIA];
      case "play":
      case "search":
      case "queue":
      case "pause":
      case "resume":
      case "skip":
      case "stop":
      case "volume":
      case "effect":
        return [THOMAS_ACCESS_CAPABILITIES.MEDIA];
      case "say":
      case "ask":
        return [THOMAS_ACCESS_CAPABILITIES.TALK];
      case "profile":
      case "wakeword":
      case "wakewords":
        return [THOMAS_ACCESS_CAPABILITIES.SETTINGS];
      default:
        return [];
    }
  }

  return {
    shouldProcessMessage,
    buildPrompt,
    getDisplayNameForUser,
    buildDiscordPromptMetadataForMessage,
    buildDiscordPromptMetadataForInteraction,
    extractLiteralReplyRequest,
    syncCommands,
    sendLongReply,
    ensureVoiceSessionForMember,
    handleDiscordPrompt,
    getInteractionRequiredCapabilities,
  };
}
