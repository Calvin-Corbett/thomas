import { spawn } from "node:child_process";

import {
  AudioPlayerStatus,
  StreamType,
  createAudioResource,
  entersState,
} from "@discordjs/voice";
import ffmpegPath from "ffmpeg-static";

import { formatSpeechText } from "./voice-text.js";
import {
  clampVolumePercent,
  formatTrackLine,
  formatYouTubeResults,
} from "./native-commands.js";
import { buildSoundEffectPath } from "./soundboard.js";
import { isPausedStatus } from "./voice-manager-shared.js";

const GENERIC_MUSIC_FALLBACK_QUERY = "top hits music";
const PENDING_PLAYBACK_QUERY_WINDOW_MS = 20_000;

export const voicePlaybackMethods = {
  summarizeTrackForSpeech(track) {
    return formatSpeechText(track?.title || "that track", 120);
  },

  getQueueSpeechSummary(state) {
    if (!state.currentTrack && state.queue.length === 0) {
      return `Nothing is playing. Volume is ${state.volumePercent} percent.`;
    }

    const parts = [];
    if (state.currentTrack) {
      parts.push(
        `${isPausedStatus(state.player.state.status) ? "Paused on" : "Now playing"} ${formatSpeechText(state.currentTrack.title, 120)}.`,
      );
    }
    if (state.queue.length > 0) {
      parts.push(`${state.queue.length} more track${state.queue.length === 1 ? "" : "s"} queued.`);
    }
    parts.push(`Volume is ${state.volumePercent} percent.`);
    return parts.join(" ");
  },

  stopPlayer(state, { clearQueue = false, suppressQueueAdvance = true } = {}) {
    state.suppressQueueAdvance = suppressQueueAdvance;
    if (state.currentPlaybackProcess) {
      state.currentPlaybackProcess.kill();
      state.currentPlaybackProcess = null;
    }
    state.currentAudioResource = null;

    if (state.player.state.status !== AudioPlayerStatus.Idle) {
      state.player.stop(true);
    } else {
      state.suppressQueueAdvance = false;
    }

    state.playbackKind = null;
    state.playbackStartedAt = 0;
    state.currentTrack = null;

    if (clearQueue) {
      state.queue = [];
    }
  },

  async startTrackPlayback(state, entry, { announce = true } = {}) {
    const { track, requestedBy = "someone", textChannelId = null, requestQuery = "" } = entry;
    await this.playStream(state, track.streamUrl, {
      playbackKind: "media",
      label: track.title,
      metadata: { track },
    });
    state.currentTrack = track;
    state.lastTrack = track;
    state.lastRequestedQuery = String(requestQuery || "").trim() || state.lastRequestedQuery;
    if (announce) {
      await this.sendLinkedText(
        state,
        `Now playing for ${requestedBy}:\n${formatTrackLine(track)}`,
        textChannelId,
      );
    }
    return track;
  },

  async playNextQueuedTrack(state) {
    if (state.destroyed || state.player.state.status !== AudioPlayerStatus.Idle || state.queue.length === 0) {
      return null;
    }

    const entry = state.queue.shift();
    if (!entry) {
      return null;
    }

    try {
      return await this.startTrackPlayback(state, entry);
    } catch (error) {
      console.warn(`[thomas-discord] Voice queued playback failed in ${state.voiceChannelName}: ${error.message}`);
      await this.sendLinkedText(
        state,
        `Thomas media error while starting the next queued track: ${error.message}`,
        entry.textChannelId,
      ).catch(() => {});
      return this.playNextQueuedTrack(state);
    }
  },

  async playStream(state, input, { playbackKind, label, metadata = null } = {}) {
    this.stopPlayer(state, { suppressQueueAdvance: true });

    const ffmpegArgs = [
      "-hide_banner",
      "-loglevel",
      "error",
      "-reconnect",
      "1",
      "-reconnect_streamed",
      "1",
      "-reconnect_delay_max",
      "5",
      "-i",
      input,
    ];

    ffmpegArgs.push("-ac", "2", "-ar", "48000", "-f", "s16le", "pipe:1");

    const ffmpeg = spawn(
      ffmpegPath,
      ffmpegArgs,
      {
        windowsHide: true,
      },
    );

    ffmpeg.stderr.on("data", () => {});
    ffmpeg.once("close", (code) => {
      if (state.currentPlaybackProcess !== ffmpeg) {
        return;
      }

      state.currentPlaybackProcess = null;
      if (
        code !== 0
        && code !== null
        && state.player.state.status !== AudioPlayerStatus.Idle
        && !state.destroyed
      ) {
        console.warn(`[thomas-discord] Voice playback process failed in ${state.voiceChannelName}: ${label} (${code})`);
      }
    });
    ffmpeg.once("error", (error) => {
      if (state.currentPlaybackProcess === ffmpeg) {
        console.warn(`[thomas-discord] Voice playback spawn failed in ${state.voiceChannelName}: ${error.message}`);
      }
    });

    const resource = createAudioResource(ffmpeg.stdout, {
      inputType: StreamType.Raw,
      inlineVolume: true,
      metadata,
    });
    resource.volume?.setVolume(Math.max(0, state.volumePercent) / 100);

    state.currentPlaybackProcess = ffmpeg;
    state.currentAudioResource = resource;
    state.playbackKind = playbackKind;
    state.playbackStartedAt = Date.now();
    state.player.play(resource);
    await entersState(state.player, AudioPlayerStatus.Playing, 15_000);
  },

  async searchYouTube({ guildId, query, textChannelId = null, limit = this.config.mediaSearchLimit }) {
    const state = this.sessions.get(guildId);
    if (!state) {
      throw new Error("Thomas is not connected to a voice channel in this server.");
    }

    const startedAt = Date.now();
    const results = await this.media.searchYouTube(query, limit);
    console.log(`[thomas-discord] Media search completed in ${Date.now() - startedAt}ms: ${query}`);
    const responseText = formatYouTubeResults(query, results);
    const posted = await this.sendLinkedText(state, responseText, textChannelId);
    return {
      posted,
      results,
      responseText,
    };
  },

  async playTrack({
    guildId,
    query,
    requestedBy = "someone",
    textChannelId = null,
    interruptCurrent = false,
    clearQueue = false,
  }) {
    const state = this.sessions.get(guildId);
    if (!state) {
      throw new Error("Thomas is not connected to a voice channel in this server.");
    }

    const startedAt = Date.now();
    const track = await this.media.resolvePlayback(query);
    console.log(`[thomas-discord] Media resolve completed in ${Date.now() - startedAt}ms: ${query} -> ${track.title}`);
    const entry = { track, requestedBy, textChannelId, requestQuery: query };
    state.lastTrack = track;
    state.lastRequestedQuery = String(query || "").trim();

    const currentlyPlaying =
      Boolean(state.currentTrack)
      || Boolean(state.currentPlaybackProcess)
      || state.player.state.status !== AudioPlayerStatus.Idle;
    if (interruptCurrent && (currentlyPlaying || state.queue.length > 0)) {
      this.stopPlayer(state, {
        clearQueue,
        suppressQueueAdvance: true,
      });
      await this.startTrackPlayback(state, entry, { announce: false });
      return {
        track,
        queued: false,
        position: 0,
        replaced: true,
      };
    }

    if (currentlyPlaying || state.queue.length > 0) {
      state.queue.push(entry);
      console.log(`[thomas-discord] Queued media in ${state.voiceChannelName}: ${track.title} (#${state.queue.length})`);
      return {
        track,
        queued: true,
        position: state.queue.length,
        replaced: false,
      };
    }

    await this.startTrackPlayback(state, entry);
    return {
      track,
      queued: false,
      position: 0,
      replaced: false,
    };
  },

  async playEffect({ guildId, effectName }) {
    const state = this.sessions.get(guildId);
    if (!state) {
      throw new Error("Thomas is not connected to a voice channel in this server.");
    }

    await this.ensureAssets();
    const effectPath = buildSoundEffectPath(this.config.dataDir, effectName);
    if (!effectPath) {
      throw new Error(`Unknown sound effect: ${effectName}`);
    }

    await this.playStream(state, effectPath, {
      playbackKind: "effect",
      label: `effect:${effectName}`,
    });
    console.log(`[thomas-discord] Played sound effect in ${state.voiceChannelName}: ${effectName}`);
    return effectName;
  },

  async stopPlayback(guildId) {
    const state = this.sessions.get(guildId);
    if (!state) {
      return { stopped: false, clearedQueueCount: 0 };
    }

    const clearedQueueCount = state.queue.length;
    if (state.player.state.status === AudioPlayerStatus.Idle && !state.currentPlaybackProcess && !state.currentTrack && clearedQueueCount === 0) {
      return { stopped: false, clearedQueueCount: 0 };
    }

    this.stopPlayer(state, { clearQueue: true, suppressQueueAdvance: true });
    return { stopped: true, clearedQueueCount };
  },

  async pausePlayback(guildId) {
    const state = this.sessions.get(guildId);
    if (!state || !state.currentTrack || isPausedStatus(state.player.state.status)) {
      return false;
    }

    return state.player.pause(true);
  },

  async resumePlayback(guildId) {
    const state = this.sessions.get(guildId);
    if (!state || !state.currentTrack || !isPausedStatus(state.player.state.status)) {
      return false;
    }

    return state.player.unpause();
  },

  async resumeOrRestartPlayback(guildId, {
    requestedBy = "someone",
    textChannelId = null,
  } = {}) {
    const state = this.sessions.get(guildId);
    if (!state) {
      return {
        resumed: false,
        restarted: false,
        alreadyPlaying: false,
        track: null,
      };
    }

    if (state.currentTrack && isPausedStatus(state.player.state.status)) {
      const resumed = await this.resumePlayback(guildId);
      return {
        resumed,
        restarted: false,
        alreadyPlaying: false,
        track: state.currentTrack,
      };
    }

    if (state.currentTrack && state.player.state.status !== AudioPlayerStatus.Idle) {
      return {
        resumed: false,
        restarted: false,
        alreadyPlaying: true,
        track: state.currentTrack,
      };
    }

    const replayTarget = state.currentTrack?.webpageUrl || state.lastTrack?.webpageUrl || state.lastRequestedQuery;
    if (!replayTarget) {
      return {
        resumed: false,
        restarted: false,
        alreadyPlaying: false,
        track: null,
      };
    }

    const result = await this.playTrack({
      guildId: state.guildId,
      query: replayTarget,
      requestedBy,
      textChannelId,
      interruptCurrent: false,
      clearQueue: false,
    });

    return {
      resumed: !result.queued,
      restarted: !result.queued,
      alreadyPlaying: false,
      track: result.track,
    };
  },

  async skipPlayback(guildId) {
    const state = this.sessions.get(guildId);
    if (!state) {
      return {
        skipped: false,
        nextTrack: null,
      };
    }

    if (state.currentTrack) {
      const nextTrack = state.queue[0]?.track || null;
      if (state.player.state.status === AudioPlayerStatus.Idle) {
        state.currentTrack = null;
        return {
          skipped: false,
          nextTrack: await this.playNextQueuedTrack(state),
        };
      }

      state.suppressQueueAdvance = false;
      state.player.stop(true);
      return {
        skipped: true,
        nextTrack,
      };
    }

    if (state.queue.length > 0) {
      return {
        skipped: false,
        nextTrack: await this.playNextQueuedTrack(state),
      };
    }

    return {
      skipped: false,
      nextTrack: null,
    };
  },

  async setVolume(guildId, volumePercent) {
    const state = this.sessions.get(guildId);
    if (!state) {
      throw new Error("Thomas is not connected to a voice channel in this server.");
    }

    const nextVolume = clampVolumePercent(volumePercent, state.volumePercent);
    const changed = nextVolume !== state.volumePercent;
    state.volumePercent = nextVolume;

    if (changed && state.currentAudioResource?.volume) {
      state.currentAudioResource.volume.setVolume(nextVolume / 100);
    }

    await this.persistRuntimeSettings({ voiceMediaVolume: nextVolume });

    return {
      volumePercent: state.volumePercent,
      restartedCurrentTrack: false,
    };
  },

  async changeVolumeByDelta(guildId, deltaPercent) {
    const state = this.sessions.get(guildId);
    if (!state) {
      throw new Error("Thomas is not connected to a voice channel in this server.");
    }
    const nextVolume = clampVolumePercent(state.volumePercent + Number(deltaPercent || 0), state.volumePercent);
    return this.setVolume(guildId, nextVolume);
  },

  async handleGenericPlayMusic(state, member) {
    state.pendingPlaybackQueryUserId = "";
    state.pendingPlaybackQueryUntil = 0;

    if (state.currentTrack && isPausedStatus(state.player.state.status)) {
      const resumed = await this.resumePlayback(state.guildId);
      return {
        action: resumed ? "resumed" : "failed",
        track: state.currentTrack,
      };
    }

    if (state.currentTrack) {
      return {
        action: "already-playing",
        track: state.currentTrack,
      };
    }

    if (state.queue.length > 0) {
      const nextTrack = await this.playNextQueuedTrack(state);
      return {
        action: nextTrack ? "queue-started" : "missing",
        track: nextTrack,
      };
    }

    const replayTarget = state.lastTrack?.webpageUrl || state.lastRequestedQuery;
    if (replayTarget) {
      const result = await this.playTrack({
        guildId: state.guildId,
        query: replayTarget,
        requestedBy: member.displayName,
        textChannelId: state.textChannelId,
      });
      return {
        action: result.queued ? "queued" : "replayed",
        track: result.track,
      };
    }

    try {
      const result = await this.playTrack({
        guildId: state.guildId,
        query: GENERIC_MUSIC_FALLBACK_QUERY,
        requestedBy: member.displayName,
        textChannelId: state.textChannelId,
      });
      return {
        action: result.queued ? "queued" : "autoplay",
        track: result.track,
      };
    } catch (error) {
      console.warn(
        `[thomas-discord] Generic play fallback failed in ${state.voiceChannelName}: ${error.message}`,
      );
    }

    state.pendingPlaybackQueryUserId = String(member?.id || "").trim();
    state.pendingPlaybackQueryUntil = Date.now() + PENDING_PLAYBACK_QUERY_WINDOW_MS;
    return {
      action: "missing",
      track: null,
    };
  },

  async handleNativeVoiceCommand(state, member, command) {
    console.log(
      `[thomas-discord] Native voice command in ${state.voiceChannelName}: ${command.type}${command.query ? ` ${command.query}` : command.effect ? ` ${command.effect}` : command.targetQuery ? ` ${command.targetQuery}` : command.volumePercent != null ? ` ${command.volumePercent}` : ""}`,
    );

    if (
      command.type === "access_grant"
      || command.type === "access_revoke"
      || command.type === "access_list"
    ) {
      await this.speakText(state.guildId, "Manage Thomas access in text chat with an at mention.");
      return true;
    }

    if (command.type === "youtube_search") {
      const { posted, results } = await this.searchYouTube({
        guildId: state.guildId,
        query: command.query,
        limit: command.limit ?? this.config.mediaSearchLimit,
      });
      if (results.length > 0) {
        await this.speakText(
          state.guildId,
          posted
            ? results.length === 1
              ? "I posted the top YouTube result in chat."
              : `I posted ${results.length} YouTube results in chat.`
            : `The top YouTube result is ${formatSpeechText(results[0].title, 120)}.`,
        );
      } else {
        await this.speakText(state.guildId, `I couldn't find a YouTube result for ${command.query}.`);
      }
      return true;
    }

    if (command.type === "join_voice_channel") {
      const targetChannel = await this.findVoiceChannelByQuery(state.guild, command.targetQuery);
      if (!targetChannel) {
        const replyText = `I couldn't find the ${command.targetQuery} voice channel.`;
        await this.speakText(state.guildId, replyText);
        return replyText;
      }
      if (targetChannel.id === state.voiceChannelId) {
        const replyText = `I'm already in ${targetChannel.name}.`;
        await this.speakText(state.guildId, replyText);
        return replyText;
      }

      await this.sendLinkedText(
        state,
        `Moving Thomas from **${state.voiceChannelName}** to **${targetChannel.name}**.`,
      ).catch(() => {});
      const joinedState = await this.joinChannel(targetChannel, {
        textChannelId: state.textChannelId,
        announce: false,
      });
      const replyText = `Joined ${targetChannel.name}.`;
      await this.speakText(joinedState.guildId, replyText);
      return replyText;
    }

    if (command.type === "leave_voice_channel") {
      const replyText = "Leaving voice now.";
      await this.speakText(state.guildId, replyText);
      await this.leaveGuild(state.guildId);
      return replyText;
    }

    if (command.type === "play") {
      const replaceCurrent =
        Boolean(state.currentTrack)
        || Boolean(state.currentPlaybackProcess)
        || state.player.state.status !== AudioPlayerStatus.Idle
        || state.queue.length > 0;
      const result = await this.playTrack({
        guildId: state.guildId,
        query: command.query,
        requestedBy: member.displayName,
        textChannelId: state.textChannelId,
        interruptCurrent: replaceCurrent,
        clearQueue: replaceCurrent,
      });
      if (result.queued) {
        await this.sendLinkedText(
          state,
          `Queued **${result.track.title}** at position ${result.position}.`,
        );
        return `Queued ${this.summarizeTrackForSpeech(result.track)}.`;
      }
      if (result.replaced) {
        await this.sendLinkedText(
          state,
          `Switching to **${result.track.title}** now.`,
        );
        return `Switching to ${this.summarizeTrackForSpeech(result.track)}.`;
      }
      return `Playing ${this.summarizeTrackForSpeech(result.track)}.`;
    }

    if (command.type === "queue_track") {
      const result = await this.playTrack({
        guildId: state.guildId,
        query: command.query,
        requestedBy: member.displayName,
        textChannelId: state.textChannelId,
      });
      if (result.queued) {
        await this.sendLinkedText(
          state,
          `Queued **${result.track.title}** at position ${result.position}.`,
        );
        return `Queued ${this.summarizeTrackForSpeech(result.track)}.`;
      }
      return `Playing ${this.summarizeTrackForSpeech(result.track)}.`;
    }

    if (command.type === "play_music") {
      const result = await this.handleGenericPlayMusic(state, member);
      if (result.action === "resumed") {
        await this.sendLinkedText(state, `Resumed **${result.track.title}**.`);
        return `Resumed ${this.summarizeTrackForSpeech(result.track)}.`;
      }
      if (result.action === "already-playing") {
        return `Already playing ${this.summarizeTrackForSpeech(result.track)}.`;
      }
      if (result.action === "queue-started" || result.action === "replayed") {
        await this.sendLinkedText(state, `Playing **${result.track.title}**.`);
        return `Playing ${this.summarizeTrackForSpeech(result.track)}.`;
      }
      if (result.action === "autoplay") {
        await this.sendLinkedText(state, `Playing **${result.track.title}**.`);
        return `Playing ${this.summarizeTrackForSpeech(result.track)}.`;
      }
      if (result.action === "queued") {
        await this.sendLinkedText(state, `Queued **${result.track.title}**.`);
        return `Queued ${this.summarizeTrackForSpeech(result.track)}.`;
      }
      await this.speakText(state.guildId, "Tell me what song you want.");
      return "Tell me what song you want.";
    }

    if (command.type === "effect") {
      await this.playEffect({
        guildId: state.guildId,
        effectName: command.effect,
      });
      return true;
    }

    if (command.type === "stop") {
      const result = await this.stopPlayback(state.guildId);
      await this.speakText(
        state.guildId,
        result.stopped
          ? result.clearedQueueCount > 0
            ? `Stopped and cleared ${result.clearedQueueCount} queued track${result.clearedQueueCount === 1 ? "" : "s"}.`
            : "Stopped."
          : "Nothing is playing.",
      );
      return true;
    }

    if (command.type === "pause") {
      const paused = await this.pausePlayback(state.guildId);
      if (paused) {
        await this.sendLinkedText(state, "Paused the current track.");
        return `Paused ${this.summarizeTrackForSpeech(state.currentTrack)}.`;
      }
      return "Nothing is playing right now.";
    }

    if (command.type === "resume") {
      const result = await this.resumeOrRestartPlayback(state.guildId, {
        requestedBy: member.displayName,
        textChannelId: state.textChannelId,
      });
      if (result.resumed && result.restarted) {
        await this.sendLinkedText(state, `Restarted **${result.track.title}**.`);
        return `Restarting ${this.summarizeTrackForSpeech(result.track)}.`;
      }
      if (result.resumed) {
        await this.sendLinkedText(state, "Resumed the current track.");
        return `Resumed ${this.summarizeTrackForSpeech(result.track)}.`;
      }
      if (result.alreadyPlaying) {
        return `Already playing ${this.summarizeTrackForSpeech(result.track)}.`;
      }
      return "Nothing is paused right now.";
    }

    if (command.type === "skip") {
      const result = await this.skipPlayback(state.guildId);
      if (!result.skipped && !result.nextTrack) {
        await this.speakText(state.guildId, "Nothing is queued right now.");
        return "Nothing is queued right now.";
      }
      if (result.nextTrack) {
        await this.sendLinkedText(state, `Skipped ahead to **${result.nextTrack.title}**.`);
        return `Skipping to ${this.summarizeTrackForSpeech(result.nextTrack)}.`;
      }
      return "Skipped the current track.";
    }

    if (command.type === "queue") {
      await this.sendLinkedText(state, this.getQueueStatus(state.guildId));
      return this.getQueueSpeechSummary(state);
    }

    if (command.type === "volume") {
      const result = await this.setVolume(state.guildId, command.volumePercent);
      await this.sendLinkedText(state, `Voice volume set to ${result.volumePercent} percent.`);
      return `Volume ${result.volumePercent} percent.`;
    }

    if (command.type === "volume_relative") {
      const result = await this.changeVolumeByDelta(state.guildId, command.deltaPercent);
      await this.sendLinkedText(state, `Voice volume set to ${result.volumePercent} percent.`);
      return `Volume ${result.volumePercent} percent.`;
    }

    if (command.type === "voice_profile") {
      const result = await this.setVoiceProfile(command.profileId);
      await this.sendLinkedText(
        state,
        result.changed
          ? `Voice profile switched to ${result.profile.label}.`
          : `Voice profile is already ${result.profile.label}.`,
      );
      return true;
    }

    if (command.type === "set_voice_wake_required") {
      const result = await this.setWakeWordRequired(command.requireWakeWord);
      await this.sendLinkedText(
        state,
        result.requireWakeWord
          ? "Wake word requirement is on."
          : "Wake word requirement is off.",
      );
      return true;
    }

    if (command.type === "set_voice_wake_words") {
      const result = await this.setWakeWords(command.wakeWords);
      await this.sendLinkedText(
        state,
        `Wake words set to: ${result.wakeWords.join(", ")}.`,
      );
      return true;
    }

    if (command.type === "status") {
      const status = this.getQueueSpeechSummary(state);
      await this.speakText(state.guildId, status);
      return status;
    }

    return false;
  },
};
