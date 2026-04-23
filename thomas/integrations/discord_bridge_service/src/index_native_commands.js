import { describeCapabilities } from "./discord-access.js";
import { formatYouTubeResults, parseNativeCommand } from "./native-commands.js";

export function createNativeMessageCommandHandler({
  config,
  voiceManager,
  sendLongReply,
  formatDelegatedAccessList,
  resolveAccessTargetMember,
  grantMemberAccess,
  revokeMemberAccess,
  ensureVoiceSessionForMember,
}) {
  return async function handleNativeMessageCommand(message, cleanedContent, parsedCommand = null) {
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

    if (command.type === "play" || command.type === "play_music") {
      const result = command.type === "play_music"
        ? await voiceManager.handleGenericPlayMusic(session, member)
        : await voiceManager.playTrack({
          guildId: message.guild.id,
          query: command.query,
          requestedBy: member.displayName || message.author.globalName || message.author.username,
          textChannelId: message.channelId,
        });
      let content = "";
      if (command.type === "play_music") {
        if (result.action === "resumed") {
          content = `Resumed **${result.track.title}** in ${session.voiceChannelName}.`;
        } else if (result.action === "already-playing") {
          content = `Already playing **${result.track.title}** in ${session.voiceChannelName}.`;
        } else if (result.action === "queue-started" || result.action === "replayed") {
          content = `Playing **${result.track.title}** in ${session.voiceChannelName}.`;
        } else if (result.action === "queued") {
          content = `Queued **${result.track.title}** in ${session.voiceChannelName}.`;
        } else {
          content = "Tell me what song you want me to play.";
        }
      } else {
        content = result.queued
          ? `Queued **${result.track.title}** at position ${result.position} in ${session.voiceChannelName}.`
          : `Playing **${result.track.title}** in ${session.voiceChannelName}.`;
      }
      await message.reply({
        content,
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
      const resumed = await voiceManager.resumeOrRestartPlayback(message.guild.id, {
        requestedBy: member.displayName || message.author.globalName || message.author.username,
        textChannelId: message.channelId,
      });
      await message.reply({
        content: resumed.resumed
          ? resumed.restarted
            ? `Restarted **${resumed.track.title}**.`
            : "Resumed the current track."
          : resumed.alreadyPlaying
            ? `Already playing **${resumed.track.title}**.`
            : "Nothing is paused right now.",
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

    if (command.type === "volume" || command.type === "volume_relative") {
      const result = command.type === "volume_relative"
        ? await voiceManager.changeVolumeByDelta(message.guild.id, command.deltaPercent)
        : await voiceManager.setVolume(message.guild.id, command.volumePercent);
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
  };
}
