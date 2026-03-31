import "dotenv/config";

import process from "node:process";
import { pathToFileURL } from "node:url";

import { Client, Events, GatewayIntentBits } from "discord.js";

import { loadConfig } from "./config.js";
import {
  THOMAS_ACCESS_CAPABILITIES,
  getRequiredCapabilityForNativeCommand,
  hasAnyCapability,
} from "./discord-access.js";
import { createAccessController } from "./bridge-access.js";
import { createBridgeHelpers } from "./bridge-helpers.js";
import { cleanDiscordPrompt } from "./discord-format.js";
import { formatYouTubeResults, parseNativeCommand } from "./native-commands.js";
import { RuntimeSettingsStore } from "./runtime-settings-store.js";
import { buildScopeKey, SessionStore } from "./session-store.js";
import { buildSlashCommands } from "./slash-commands.js";
import { ThomasClient } from "./thomas-client.js";
import { VoiceManager } from "./voice-manager.js";

export async function main() {
  const config = loadConfig();
  const settingsStore = new RuntimeSettingsStore({
    dataDir: config.dataDir,
    defaults: {
      requireMention: config.requireMention,
      voiceRequireWakeWord: config.voiceRequireWakeWord,
      voiceWakeWords: config.voiceWakeWords,
      voiceMediaVolume: config.voiceMediaVolume,
      voiceProfile: config.voiceTtsModel,
      accessGrants: {},
    },
  });
  await settingsStore.ensureLoaded();
  const runtimeSettings = settingsStore.getState();
  const runtimeConfig = {
    ...config,
    requireMention: runtimeSettings.requireMention,
    voiceRequireWakeWord: runtimeSettings.voiceRequireWakeWord,
    voiceWakeWords: runtimeSettings.voiceWakeWords,
    voiceMediaVolume: runtimeSettings.voiceMediaVolume,
    voiceTtsModel: runtimeSettings.voiceProfile || config.voiceTtsModel,
  };
  const slashCommands = buildSlashCommands(runtimeConfig);
  const client = new Client({
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildMessages,
      GatewayIntentBits.GuildMembers,
      GatewayIntentBits.GuildVoiceStates,
      GatewayIntentBits.DirectMessages,
      GatewayIntentBits.MessageContent,
    ],
  });

  const sessionStore = new SessionStore({
    dataDir: config.dataDir,
    sessionPrefix: config.sessionPrefix,
  });

  const thomas = new ThomasClient({
    baseUrl: config.thomasBaseUrl,
    apiToken: config.thomasApiToken,
    timeoutMs: config.thomasTimeoutMs,
  });

  const scopeQueues = new Map();
  const access = createAccessController({ config, settingsStore });
  const {
    buildAccessDeniedMessage,
    canUserManageSettings,
    canUserTalk,
    canUserUseCapability,
    canUserUseMedia,
    formatDelegatedAccessList,
    getAccessContext,
    getUserCapabilities,
    grantMemberAccess,
    isGuildAllowed,
    isOwnerUser,
    resolveAccessTargetMember,
    revokeMemberAccess,
  } = access;

  const voiceManager = new VoiceManager({
    client,
    config: runtimeConfig,
    thomas,
    sessionStore,
    settingsStore,
    enqueueByScope,
    isOwnerUser,
    canUserUseCapability,
  });

  const {
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
  } = createBridgeHelpers({
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
  });

  async function enqueueByScope(scopeKey, task) {
    const previous = scopeQueues.get(scopeKey) || Promise.resolve();
    const next = previous.catch(() => {}).then(task);
    scopeQueues.set(
      scopeKey,
      next.finally(() => {
        if (scopeQueues.get(scopeKey) === next) {
          scopeQueues.delete(scopeKey);
        }
      }),
    );
    return next;
  }

  async function handleNativeMessageCommand(message, cleanedContent, parsedCommand = null) {
    if (!message.guild) {
      return false;
    }

    const command = parsedCommand || parseNativeCommand(cleanedContent);
    if (!command) {
      return false;
    }

    if (command.type === "youtube_search") {
      const session = voiceManager.getSession(message.guild.id);
      if (session) {
        await voiceManager.updateLinkedTextChannel(message.guild.id, message.channelId);
      }

      const results = await voiceManager.media.searchYouTube(
        command.query,
        command.limit ?? config.mediaSearchLimit,
      );
      await sendLongReply(message.channel, formatYouTubeResults(command.query, results), {
        replyToMessage: message,
      });
      return true;
    }

    if (command.type === "access_list") {
      await sendLongReply(message.channel, await formatDelegatedAccessList(message.guild), {
        replyToMessage: message,
      });
      return true;
    }

    if (command.type === "access_grant") {
      const targetMember = await resolveAccessTargetMember(message.guild, command);
      const result = await grantMemberAccess(targetMember, command.capabilities, message.author.id);
      await message.reply({
        content: result.owner
          ? `${targetMember.displayName} is the owner and already has full access.`
          : result.changed
            ? `Granted ${targetMember.displayName} ${describeCapabilities(result.grant.capabilities)} to Thomas.`
            : `${targetMember.displayName} already has ${describeCapabilities(result.grant.capabilities)}.`,
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "access_revoke") {
      const targetMember = await resolveAccessTargetMember(message.guild, command);
      const result = await revokeMemberAccess(targetMember);
      await message.reply({
        content: result.owner
          ? `${targetMember.displayName} is the owner and cannot be removed.`
          : result.changed
            ? `Removed ${targetMember.displayName}'s Thomas access.`
            : `${targetMember.displayName} did not have delegated Thomas access.`,
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    const member = await message.guild.members.fetch(message.author.id);

    if (command.type === "voice_profile") {
      const result = await voiceManager.setVoiceProfile(command.profileId);
      await message.reply({
        content: result.changed
          ? `Switched Thomas to **${result.profile.label}**.`
          : `Thomas is already using **${result.profile.label}**.`,
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "set_text_mentions") {
      const result = await voiceManager.setTextMentionMode(command.requireMention);
      await message.reply({
        content: result.requireMention
          ? "Thomas will now reply only when mentioned."
          : "Thomas will now reply in allowed channels without needing a mention.",
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "set_voice_wake_required") {
      const result = await voiceManager.setWakeWordRequired(command.requireWakeWord);
      await message.reply({
        content: result.requireWakeWord
          ? "Wake-word requirement is on."
          : "Wake-word requirement is off.",
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "set_voice_wake_words") {
      const result = await voiceManager.setWakeWords(command.wakeWords);
      await message.reply({
        content: `Wake words set to: ${result.wakeWords.join(", ")}.`,
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "join_voice_channel") {
      const targetChannel = await voiceManager.findVoiceChannelByQuery(message.guild, command.targetQuery);
      if (!targetChannel) {
        await message.reply({
          content: `I couldn't find the ${command.targetQuery} voice channel.`,
          allowedMentions: { repliedUser: false },
        });
        return true;
      }

      const joinedSession = await voiceManager.joinChannel(targetChannel, {
        textChannelId: message.channelId,
        announce: false,
      });
      await message.reply({
        content: `Thomas joined ${joinedSession.voiceChannelName}.`,
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "leave_voice_channel") {
      const existing = voiceManager.getSession(message.guild.id);
      if (!existing) {
        await message.reply({
          content: "Thomas is not in a voice channel right now.",
          allowedMentions: { repliedUser: false },
        });
        return true;
      }

      await voiceManager.leaveGuild(message.guild.id);
      await message.reply({
        content: "Thomas left the voice channel.",
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    const session = await ensureVoiceSessionForMember(member, message.channelId);

    if (command.type === "play") {
      const result = await voiceManager.playTrack({
        guildId: message.guild.id,
        query: command.query,
        requestedBy: member.displayName || message.author.globalName || message.author.username,
        textChannelId: message.channelId,
      });
      await message.reply({
        content: result.queued
          ? `Queued **${result.track.title}** at position ${result.position} in ${session.voiceChannelName}.`
          : `Playing **${result.track.title}** in ${session.voiceChannelName}.`,
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "effect") {
      const effectName = await voiceManager.playEffect({
        guildId: message.guild.id,
        effectName: command.effect,
      });
      await message.reply({
        content: `Played \`${effectName}\` in ${session.voiceChannelName}.`,
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "stop") {
      const result = await voiceManager.stopPlayback(message.guild.id);
      await message.reply({
        content: result.stopped
          ? result.clearedQueueCount > 0
            ? `Stopped voice playback and cleared ${result.clearedQueueCount} queued track${result.clearedQueueCount === 1 ? "" : "s"}.`
            : "Stopped voice playback."
          : "Nothing is playing right now.",
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "pause") {
      const paused = await voiceManager.pausePlayback(message.guild.id);
      await message.reply({
        content: paused ? "Paused the current track." : "Nothing is playing right now.",
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "resume") {
      const resumed = await voiceManager.resumePlayback(message.guild.id);
      await message.reply({
        content: resumed ? "Resumed the current track." : "Nothing is paused right now.",
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "skip") {
      const result = await voiceManager.skipPlayback(message.guild.id);
      await message.reply({
        content: result.skipped || result.nextTrack
          ? result.nextTrack
            ? `Skipped ahead to **${result.nextTrack.title}**.`
            : "Skipped the current track."
          : "Nothing is playing right now.",
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "queue") {
      await sendLongReply(message.channel, voiceManager.getQueueStatus(message.guild.id), {
        replyToMessage: message,
      });
      return true;
    }

    if (command.type === "volume") {
      const result = await voiceManager.setVolume(message.guild.id, command.volumePercent);
      await message.reply({
        content: `Set voice volume to ${result.volumePercent}%.`,
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    if (command.type === "status") {
      await message.reply({
        content: voiceManager.getQueueStatus(message.guild.id),
        allowedMentions: { repliedUser: false },
      });
      return true;
    }

    return false;
  }

  client.once(Events.ClientReady, async (readyClient) => {
    console.log(`[thomas-discord] Logged in as ${readyClient.user.tag}`);
    await syncCommands();
    await voiceManager.autoJoinConfiguredChannels();
  });

  client.on(Events.MessageCreate, async (message) => {
    if (!shouldProcessMessage(message)) {
      return;
    }

    const cleanedContent = cleanDiscordPrompt(message.content, client.user?.id);
    if (!cleanedContent && message.attachments.size === 0) {
      return;
    }

    const parsedCommand = parseNativeCommand(cleanedContent);
    const requiredCapability = getRequiredCapabilityForNativeCommand(parsedCommand);

    if (parsedCommand && requiredCapability && !canUserUseCapability(message.author.id, requiredCapability)) {
      if (getUserCapabilities(message.author.id).length > 0 || requiredCapability === THOMAS_ACCESS_CAPABILITIES.SETTINGS) {
        await message.reply({
          content: buildAccessDeniedMessage(requiredCapability, message.author.id),
          allowedMentions: { repliedUser: false },
        });
      }
      return;
    }

    if (!parsedCommand && !canUserTalk(message.author.id)) {
      return;
    }

    const literalReply = message.attachments.size === 0 ? extractLiteralReplyRequest(cleanedContent) : null;
    if (literalReply) {
      await message.reply({
        content: literalReply,
        allowedMentions: { repliedUser: false },
      });
      return;
    }

    try {
      if (await handleNativeMessageCommand(message, cleanedContent, parsedCommand)) {
        return;
      }
    } catch (error) {
      const details = error instanceof Error ? error.message : String(error);
      await message.reply({
        content: `Thomas media error: ${details}`,
        allowedMentions: { repliedUser: false },
      });
      return;
    }

    const scopeKey = buildScopeKey(message);
    const prompt = buildPrompt({ message, cleanedContent });

    await enqueueByScope(scopeKey, async () => {
      const sessionId = await sessionStore.getSessionId(scopeKey);
      await message.channel.sendTyping();
      try {
        await handleDiscordPrompt({
          scopeKey,
          sessionId,
          prompt,
          replyTarget: message.channel,
          replyToMessage: message,
        });
      } catch (error) {
        const details = error instanceof Error ? error.message : String(error);
        await message.reply({
          content: `Thomas bridge error: ${details}`,
          allowedMentions: { repliedUser: false },
        });
      }
    });
  });

  client.on(Events.InteractionCreate, async (interaction) => {
    if (!interaction.isChatInputCommand()) {
      return;
    }

    if (interaction.guildId && !isGuildAllowed(interaction.guildId)) {
      await interaction.reply({ content: "This server is not allowlisted for Thomas.", ephemeral: true });
      return;
    }

    const requiredCapabilities = getInteractionRequiredCapabilities(interaction);
    if (!hasAnyCapability(getAccessContext(), interaction.user.id, requiredCapabilities)) {
      await interaction.reply({
        content: buildAccessDeniedMessage(requiredCapabilities[0], interaction.user.id),
        ephemeral: true,
      });
      return;
    }

    const scopeKey = interaction.guildId
      ? `guild:${interaction.guildId}:channel:${interaction.channelId}`
      : `dm:${interaction.user.id}`;

    if (interaction.commandName === "reset") {
      const sessionId = await sessionStore.reset(scopeKey);
      await interaction.reply({
        content: `Reset Thomas context for this scope.\nNew session: \`${sessionId}\``,
        ephemeral: true,
      });
      return;
    }

    if (interaction.commandName === "status") {
      const sessionId = await sessionStore.getSessionId(scopeKey);
      const settings = settingsStore.getState();
      await interaction.reply({
        content: [
          `Thomas URL: ${config.thomasBaseUrl}`,
          `Owner-only mode: ${config.ownerOnlyMode}`,
          `Mention required: ${settings.requireMention}`,
          `Allowed guild filter active: ${config.allowedGuildIds.size > 0}`,
          `Wake word required: ${settings.voiceRequireWakeWord}`,
          `Wake words: ${settings.voiceWakeWords.join(", ")}`,
          `Delegated access entries: ${Object.keys(settings.accessGrants || {}).length}`,
          `Current session: \`${sessionId}\``,
          interaction.guildId ? voiceManager.getStatus(interaction.guildId) : "Voice: unavailable in DMs",
        ].join("\n"),
        ephemeral: true,
      });
      return;
    }

    if (interaction.commandName === "thomas") {
      const promptText = interaction.options.getString("message", true).trim();
      await interaction.deferReply();

      await enqueueByScope(scopeKey, async () => {
        const sessionId = await sessionStore.getSessionId(scopeKey);
        const metadata = buildDiscordPromptMetadataForInteraction(interaction, scopeKey, "thomas");
        const prompt = [
          `Reply naturally to ${getDisplayNameForUser(interaction.user, interaction.member)}.`,
          `User said: ${promptText}`,
        ].join(" ");

        try {
          let result = await thomas.sendMessage({
            sessionId,
            prompt,
            metadata,
          });

          if (replyLooksInternal(result.text)) {
            const retrySessionId = await sessionStore.reset(scopeKey);
            result = await thomas.sendMessage({
              sessionId: retrySessionId,
              prompt: buildRetryPrompt(prompt),
              metadata: {
                ...metadata,
                retried_after_internal_reply: true,
              },
            });

            if (replyLooksInternal(result.text)) {
              await sessionStore.reset(scopeKey);
            }
          }

          const parts = splitForDiscord(
            sanitizeDiscordReply(result.text),
            config.maxReplyChars,
          );
          await interaction.editReply(parts[0]);
          for (const part of parts.slice(1)) {
            await interaction.followUp(part);
          }
        } catch (error) {
          const details = error instanceof Error ? error.message : String(error);
          if (interaction.deferred || interaction.replied) {
            await interaction.editReply(`Thomas bridge error: ${details}`);
          } else {
            await interaction.reply({ content: `Thomas bridge error: ${details}`, ephemeral: true });
          }
        }
      });
      return;
    }

    if (interaction.commandName === "voice") {
      const subcommand = interaction.options.getSubcommand();

      try {
        if (subcommand === "status") {
          await interaction.reply({
            content: interaction.guildId
              ? voiceManager.getStatus(interaction.guildId)
              : "Voice controls only work in a server.",
            ephemeral: true,
          });
          return;
        }

        if (!interaction.guildId) {
          await interaction.reply({ content: "Voice controls only work in a server.", ephemeral: true });
          return;
        }

        if (subcommand === "leave") {
          await voiceManager.leaveGuild(interaction.guildId);
          await interaction.reply({ content: "Thomas left the voice channel.", ephemeral: true });
          return;
        }

        if (subcommand === "stop") {
          const result = await voiceManager.stopPlayback(interaction.guildId);
          await interaction.reply({
            content: result.stopped
              ? result.clearedQueueCount > 0
                ? `Stopped voice playback and cleared ${result.clearedQueueCount} queued track${result.clearedQueueCount === 1 ? "" : "s"}.`
                : "Stopped voice playback."
              : "Nothing is playing right now.",
            ephemeral: true,
          });
          return;
        }

        if (subcommand === "queue") {
          await interaction.reply({
            content: voiceManager.getQueueStatus(interaction.guildId),
            ephemeral: true,
          });
          return;
        }

        if (subcommand === "pause") {
          const paused = await voiceManager.pausePlayback(interaction.guildId);
          await interaction.reply({
            content: paused ? "Paused the current track." : "Nothing is playing right now.",
            ephemeral: true,
          });
          return;
        }

        if (subcommand === "resume") {
          const resumed = await voiceManager.resumePlayback(interaction.guildId);
          await interaction.reply({
            content: resumed ? "Resumed the current track." : "Nothing is paused right now.",
            ephemeral: true,
          });
          return;
        }

        if (subcommand === "skip") {
          const result = await voiceManager.skipPlayback(interaction.guildId);
          await interaction.reply({
            content: result.skipped || result.nextTrack
              ? result.nextTrack
                ? `Skipped ahead to ${result.nextTrack.title}.`
                : "Skipped the current track."
              : "Nothing is playing right now.",
            ephemeral: true,
          });
          return;
        }

        if (subcommand === "volume") {
          const result = await voiceManager.setVolume(
            interaction.guildId,
            interaction.options.getInteger("percent", true),
          );
          await interaction.reply({
            content: `Set voice volume to ${result.volumePercent}%.`,
            ephemeral: true,
          });
          return;
        }

        if (subcommand === "profile") {
          const profileId = interaction.options.getString("name", true);
          const result = await voiceManager.setVoiceProfile(profileId);
          await interaction.reply({
            content: result.changed
              ? `Switched Thomas to ${result.profile.label}.`
              : `Thomas is already using ${result.profile.label}.`,
            ephemeral: true,
          });
          return;
        }

        if (subcommand === "wakeword") {
          const result = await voiceManager.setWakeWordRequired(
            interaction.options.getBoolean("enabled", true),
          );
          await interaction.reply({
            content: result.requireWakeWord
              ? "Wake-word requirement is on."
              : "Wake-word requirement is off.",
            ephemeral: true,
          });
          return;
        }

        if (subcommand === "wakewords") {
          const words = interaction.options.getString("words", true)
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean);
          const result = await voiceManager.setWakeWords(words);
          await interaction.reply({
            content: `Wake words set to: ${result.wakeWords.join(", ")}.`,
            ephemeral: true,
          });
          return;
        }

        await interaction.deferReply({ ephemeral: true });
        const member = await interaction.guild.members.fetch(interaction.user.id);
        const currentSession = voiceManager.getSession(interaction.guildId);
        const joinedSession = currentSession || (await voiceManager.joinFromInteraction(interaction));
        await voiceManager.updateLinkedTextChannel(interaction.guildId, interaction.channelId);

        if (subcommand === "join") {
          await interaction.editReply(
            voiceManager.isVoiceWakeWordRequired()
              ? `Thomas joined ${joinedSession.voiceChannelName} and is listening for ${voiceManager.getVoiceWakeWords().join(", ")}.`
              : `Thomas joined ${joinedSession.voiceChannelName} and is listening.`,
          );
          return;
        }

        if (subcommand === "play") {
          const query = interaction.options.getString("query", true).trim();
          const result = await voiceManager.playTrack({
            guildId: interaction.guildId,
            query,
            requestedBy: member.displayName || interaction.user.globalName || interaction.user.username,
            textChannelId: interaction.channelId,
          });
          await interaction.editReply(
            result.queued
              ? `Queued ${result.track.title} at position ${result.position} in ${joinedSession.voiceChannelName}.`
              : `Playing ${result.track.title} in ${joinedSession.voiceChannelName}.`,
          );
          return;
        }

        if (subcommand === "search") {
          const query = interaction.options.getString("query", true).trim();
          const { results } = await voiceManager.searchYouTube({
            guildId: interaction.guildId,
            query,
            textChannelId: interaction.channelId,
          });
          await interaction.editReply(
            results.length > 0
              ? `Posted ${results.length} YouTube result${results.length === 1 ? "" : "s"} in chat.`
              : `No YouTube results found for "${query}".`,
          );
          return;
        }

        if (subcommand === "effect") {
          const effectName = interaction.options.getString("name", true);
          await voiceManager.playEffect({
            guildId: interaction.guildId,
            effectName,
          });
          await interaction.editReply(`Played ${effectName} in ${joinedSession.voiceChannelName}.`);
          return;
        }

        if (subcommand === "say") {
          const message = interaction.options.getString("message", true).trim();
          await voiceManager.speakText(interaction.guildId, message);
          await interaction.editReply(`Thomas spoke in ${joinedSession.voiceChannelName}.`);
          return;
        }

        if (subcommand === "ask") {
          const message = interaction.options.getString("message", true).trim();
          const replyText = await voiceManager.askThomasInVoice({
            guildId: interaction.guildId,
            speakerName: member.displayName || interaction.user.globalName || interaction.user.username,
            speakerId: interaction.user.id,
            text: message,
          });

          const preview = splitForDiscord(replyText || "Thomas answered in voice.", config.maxReplyChars)[0];
          await interaction.editReply(`Thomas answered in ${joinedSession.voiceChannelName}: ${preview}`);
          return;
        }
      } catch (error) {
        const details = error instanceof Error ? error.message : String(error);
        if (interaction.deferred || interaction.replied) {
          await interaction.editReply(`Thomas voice error: ${details}`);
        } else {
          await interaction.reply({ content: `Thomas voice error: ${details}`, ephemeral: true });
        }
      }
    }
  });

  await client.login(config.discordToken);
  return client;
}

const entryHref = process.argv[1] ? pathToFileURL(process.argv[1]).href : null;
if (entryHref && import.meta.url === entryHref) {
  main().catch((error) => {
    console.error("[thomas-discord] Fatal startup error");
    console.error(error);
    process.exitCode = 1;
  });
}
