import fsPromises from "node:fs/promises";

import {
  AudioPlayerStatus,
  NoSubscriberBehavior,
  VoiceConnectionStatus,
  createAudioPlayer,
  entersState,
  joinVoiceChannel,
} from "@discordjs/voice";

import { THOMAS_ACCESS_CAPABILITIES } from "./discord-access.js";
import { clampVolumePercent, formatQueueStatus } from "./native-commands.js";
import { ensureDefaultSoundEffects, listSoundEffects } from "./soundboard.js";
import { discoverPiperVoiceProfiles, formatVoiceProfileLabel, resolveVoiceProfile } from "./voice-profiles.js";
import { isPausedStatus, isVoiceChannel, normalizeVoiceChannelLookup } from "./voice-manager-shared.js";

export const voiceSessionMethods = {
  async autoJoinConfiguredChannels() {
    await this.ensureAssets();
    if (!this.config.voiceAutoJoin || !this.config.defaultVoiceChannelName) {
      return;
    }

    const targetGuildIds = this.config.guildId
      ? [this.config.guildId]
      : [...this.config.allowedGuildIds.values()];

    for (const guildId of targetGuildIds) {
      try {
        const guild = await this.client.guilds.fetch(guildId);
        const channel = await this.findConfiguredVoiceChannel(guild);
        if (!channel) {
          console.warn(
            `[thomas-discord] Voice auto-join skipped for guild ${guildId}: channel "${this.config.defaultVoiceChannelName}" not found`,
          );
          continue;
        }

        await this.joinChannel(channel, {
          textChannelId: null,
          announce: this.config.voiceAnnounceOnJoin,
          announceText: "Thomas is online in voice.",
        });
        console.log(`[thomas-discord] Voice auto-joined ${guild.name} / ${channel.name}`);
      } catch (error) {
        console.warn(`[thomas-discord] Voice auto-join failed for guild ${guildId}: ${error.message}`);
      }
    }
  },

  getRuntimeSettings() {
    return this.settingsStore?.getState?.() || {
      requireMention: this.config.requireMention,
      voiceRequireWakeWord: this.config.voiceRequireWakeWord,
      voiceWakeWords: [...this.config.voiceWakeWords],
      voiceMediaVolume: this.config.voiceMediaVolume,
      voiceProfile: this.ttsRuntime.model,
    };
  },

  getVoiceWakeWords() {
    return this.getRuntimeSettings().voiceWakeWords;
  },

  isVoiceWakeWordRequired() {
    return this.getRuntimeSettings().voiceRequireWakeWord;
  },

  isOwnerOnlyMode() {
    return Boolean(this.config.ownerOnlyMode);
  },

  canUserTalk(userId) {
    return this.canUserUseCapability(userId, THOMAS_ACCESS_CAPABILITIES.TALK);
  },

  canUserUseMedia(userId) {
    return this.canUserUseCapability(userId, THOMAS_ACCESS_CAPABILITIES.MEDIA);
  },

  getSession(guildId) {
    return this.sessions.get(guildId) || null;
  },

  async ensureAssets() {
    if (!this.assetsReadyPromise) {
      this.assetsReadyPromise = ensureDefaultSoundEffects(this.config.dataDir).catch((error) => {
        this.assetsReadyPromise = null;
        throw error;
      });
    }

    await this.assetsReadyPromise;
  },

  async resolveLinkedTextChannel(state, preferredChannelId = null) {
    const candidateIds = [
      preferredChannelId,
      state?.textChannelId,
      ...this.config.autoChannelIds,
      state?.guild?.systemChannelId || null,
    ].filter(Boolean);

    for (const channelId of candidateIds) {
      try {
        const channel = await state.guild.channels.fetch(channelId);
        if (channel?.isTextBased?.()) {
          if (state.textChannelId !== channel.id) {
            state.textChannelId = channel.id;
          }
          return channel;
        }
      } catch {}
    }

    return null;
  },

  async sendLinkedText(state, content, preferredChannelId = null) {
    const channel = await this.resolveLinkedTextChannel(state, preferredChannelId);
    if (!channel) {
      console.warn(`[thomas-discord] No linked text channel available for ${state.voiceChannelName}`);
      return false;
    }

    await channel.send(content);
    return true;
  },

  async findConfiguredVoiceChannel(guild) {
    if (!this.config.defaultVoiceChannelName) {
      return null;
    }

    const channels = await guild.channels.fetch();
    const wanted = this.config.defaultVoiceChannelName.toLowerCase();
    return (
      [...channels.values()].find(
        (channel) => isVoiceChannel(channel) && channel.name.toLowerCase() === wanted,
      ) || null
    );
  },

  async findVoiceChannelByQuery(guild, query) {
    const wanted = normalizeVoiceChannelLookup(query);
    if (!wanted) {
      return null;
    }

    const channels = [...(await guild.channels.fetch()).values()].filter(isVoiceChannel);
    return (
      channels.find((channel) => normalizeVoiceChannelLookup(channel.name) === wanted)
      || channels.find((channel) => normalizeVoiceChannelLookup(channel.name).includes(wanted))
      || channels.find((channel) => wanted.includes(normalizeVoiceChannelLookup(channel.name)))
      || null
    );
  },

  async updateLinkedTextChannel(guildId, textChannelId) {
    const state = this.sessions.get(guildId);
    if (!state || !textChannelId) {
      return state;
    }

    state.textChannelId = textChannelId;
    return state;
  },

  async resolveVoiceChannelForInteraction(interaction) {
    if (!interaction.guild) {
      throw new Error("Voice controls only work in a server.");
    }

    const member = await interaction.guild.members.fetch(interaction.user.id);
    if (isVoiceChannel(member.voice?.channel)) {
      return member.voice.channel;
    }

    const configured = await this.findConfiguredVoiceChannel(interaction.guild);
    if (configured) {
      return configured;
    }

    throw new Error("Join a voice channel first, or set DISCORD_DEFAULT_VOICE_CHANNEL_NAME.");
  },

  async joinFromInteraction(interaction) {
    const voiceChannel = await this.resolveVoiceChannelForInteraction(interaction);
    const wakeWords = this.getVoiceWakeWords();
    return this.joinChannel(voiceChannel, {
      textChannelId: interaction.channelId,
      announce: this.config.voiceAnnounceOnJoin,
      announceText: this.isVoiceWakeWordRequired()
        ? `Thomas is in the voice channel and listening for ${wakeWords.join(", ")}.`
        : "Thomas is in the voice channel and listening.",
    });
  },

  async joinChannel(voiceChannel, { textChannelId = null, announce = false, announceText = "", forceReconnect = false } = {}) {
    await this.ensureAssets();
    if (!isVoiceChannel(voiceChannel)) {
      throw new Error("Target channel is not a standard voice channel.");
    }

    const existing = this.sessions.get(voiceChannel.guild.id);
    if (existing && existing.voiceChannelId === voiceChannel.id && !forceReconnect) {
      existing.textChannelId = textChannelId || existing.textChannelId;
      return existing;
    }

    if (existing && !forceReconnect && existing.connection?.state?.status !== VoiceConnectionStatus.Destroyed) {
      try {
        existing.connection.rejoin({
          channelId: voiceChannel.id,
          guildId: voiceChannel.guild.id,
          adapterCreator: voiceChannel.guild.voiceAdapterCreator,
          selfDeaf: false,
          selfMute: false,
        });
        await entersState(existing.connection, VoiceConnectionStatus.Ready, 20_000);
        existing.guild = voiceChannel.guild;
        existing.voiceChannelId = voiceChannel.id;
        existing.voiceChannelName = voiceChannel.name;
        existing.textChannelId = textChannelId || existing.textChannelId;
        console.log(`[thomas-discord] Voice moved ${voiceChannel.guild.name} / ${voiceChannel.name}`);

        if (announce && announceText) {
          try {
            await this.speakText(existing.guildId, announceText);
          } catch (error) {
            console.warn(`[thomas-discord] Voice move announcement failed in ${existing.voiceChannelName}: ${error.message}`);
          }
        }

        return existing;
      } catch (error) {
        console.warn(`[thomas-discord] Voice rejoin failed in ${existing.voiceChannelName}: ${error.message}`);
      }
    }

    if (existing) {
      await this.leaveGuild(existing.guildId);
    }

    const connection = joinVoiceChannel({
      channelId: voiceChannel.id,
      guildId: voiceChannel.guild.id,
      adapterCreator: voiceChannel.guild.voiceAdapterCreator,
      selfDeaf: false,
      selfMute: false,
    });

    await entersState(connection, VoiceConnectionStatus.Ready, 20_000);

    const player = createAudioPlayer({
      behaviors: {
        noSubscriber: NoSubscriberBehavior.Pause,
      },
    });
    connection.subscribe(player);

    const state = {
      guildId: voiceChannel.guild.id,
      guild: voiceChannel.guild,
      voiceChannelId: voiceChannel.id,
      voiceChannelName: voiceChannel.name,
      connection,
      player,
      textChannelId: textChannelId || voiceChannel.guild.systemChannelId || [...this.config.autoChannelIds][0] || null,
      listeningUsers: new Set(),
      lastTranscriptByUser: new Map(),
      lastSpokenText: "",
      lastSpokenAt: 0,
      playbackKind: null,
      playbackStartedAt: 0,
      currentPlaybackProcess: null,
      currentAudioResource: null,
      currentTrack: null,
      queue: [],
      volumePercent: clampVolumePercent(this.getRuntimeSettings().voiceMediaVolume),
      suppressQueueAdvance: false,
      ignoredUntilByUser: new Map(),
      destroyed: false,
      speakingHandler: null,
      reconnectTimer: null,
    };

    state.speakingHandler = (userId) => {
      void this.handleSpeakingStart(state, userId);
    };

    connection.receiver.speaking.on("start", state.speakingHandler);
    connection.on("stateChange", (_oldState, newState) => {
      if (newState.status === VoiceConnectionStatus.Disconnected && !state.destroyed) {
        console.warn(`[thomas-discord] Voice disconnected from ${state.voiceChannelName}`);
        this.scheduleReconnect(state, `state:${newState.status}`);
      }
    });
    connection.on("error", (error) => {
      if (state.destroyed) {
        return;
      }
      console.warn(`[thomas-discord] Voice connection error in ${state.voiceChannelName}: ${error.message}`);
      this.scheduleReconnect(state, error.message);
    });
    player.on("stateChange", (oldState, newState) => {
      if (oldState.status !== AudioPlayerStatus.Idle && newState.status === AudioPlayerStatus.Idle) {
        const finishedKind = state.playbackKind;
        if (state.currentPlaybackProcess) {
          state.currentPlaybackProcess.kill();
          state.currentPlaybackProcess = null;
        }
        if (finishedKind && finishedKind !== "speech") {
          console.log(`[thomas-discord] Voice playback finished in ${state.voiceChannelName}: ${finishedKind}`);
        }
        if (finishedKind !== "speech") {
          state.playbackKind = null;
          state.playbackStartedAt = 0;
          state.currentTrack = null;
        }
        state.currentAudioResource = null;

        const shouldAdvanceQueue = !state.destroyed && !state.suppressQueueAdvance && state.queue.length > 0;
        state.suppressQueueAdvance = false;
        if (shouldAdvanceQueue) {
          void this.playNextQueuedTrack(state);
        }
      }
    });
    player.on("error", (error) => {
      console.warn(`[thomas-discord] Voice playback error in ${state.voiceChannelName}: ${error.message}`);
    });

    this.sessions.set(state.guildId, state);
    console.log(`[thomas-discord] Voice joined ${voiceChannel.guild.name} / ${voiceChannel.name}`);

    if (announce && announceText) {
      try {
        await this.speakText(state.guildId, announceText);
      } catch (error) {
        console.warn(`[thomas-discord] Voice announcement failed in ${state.voiceChannelName}: ${error.message}`);
      }
    }

    return state;
  },

  async leaveGuild(guildId) {
    const state = this.sessions.get(guildId);
    if (!state) {
      return;
    }

    state.destroyed = true;
    if (state.reconnectTimer) {
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = null;
    }
    state.connection.receiver.speaking.off("start", state.speakingHandler);
    this.stopPlayer(state);
    state.connection.destroy();
    this.sessions.delete(guildId);
  },

  scheduleReconnect(state, reason) {
    if (!state || state.destroyed || state.reconnectTimer) {
      return;
    }

    state.reconnectTimer = setTimeout(() => {
      state.reconnectTimer = null;
      void this.reconnectVoiceState(state, reason);
    }, 1_500);
  },

  async reconnectVoiceState(state, reason) {
    if (!state || state.destroyed) {
      return;
    }

    const channel = await state.guild.channels.fetch(state.voiceChannelId).catch(() => null);
    if (!isVoiceChannel(channel)) {
      console.warn(
        `[thomas-discord] Voice reconnect skipped in ${state.voiceChannelName}: channel unavailable after ${reason}`,
      );
      return;
    }

    console.warn(`[thomas-discord] Voice reconnecting ${state.voiceChannelName} after ${reason}`);
    try {
      await this.joinChannel(channel, {
        textChannelId: state.textChannelId,
        announce: false,
        forceReconnect: true,
      });
    } catch (error) {
      console.warn(`[thomas-discord] Voice reconnect failed in ${state.voiceChannelName}: ${error.message}`);
    }
  },

  getStatus(guildId) {
    const state = this.sessions.get(guildId);
    if (!state) {
      return "Voice: offline";
    }

    return [
      `Voice: connected to ${state.voiceChannelName}`,
      `Speech: ${this.speech.describeSynthesizer()}`,
      `Voice profile: ${this.getVoiceProfileStatus()}`,
      `Speech-to-text: ${this.speech.describeTranscriber()}`,
      `Wake word required: ${this.isVoiceWakeWordRequired()}`,
      `Wake words: ${this.getVoiceWakeWords().join(", ")}`,
      `Playback: ${state.currentTrack ? `media (${state.currentTrack.title})` : state.playbackKind || "idle"}`,
      `Queue length: ${state.queue.length}`,
      `Volume: ${state.volumePercent}%`,
      `Effects: ${listSoundEffects().join(", ")}`,
    ].join("\n");
  },

  getQueueStatus(guildId) {
    const state = this.sessions.get(guildId);
    if (!state) {
      return "Voice: offline";
    }

    return formatQueueStatus({
      currentTrack: state.currentTrack,
      queue: state.queue.map((entry) => entry.track),
      paused: isPausedStatus(state.player.state.status),
      volumePercent: state.volumePercent,
    });
  },

  getVoiceProfileStatus() {
    return formatVoiceProfileLabel(this.ttsRuntime.model, this.voiceProfiles);
  },

  getAvailableVoiceProfiles() {
    return this.voiceProfiles.map((profile) => `${profile.label} (\`${profile.id}\`)`).join(", ");
  },

  async persistRuntimeSettings(patch) {
    if (!this.settingsStore?.update) {
      return this.getRuntimeSettings();
    }
    return this.settingsStore.update(patch);
  },

  async setVoiceProfile(profileInput) {
    if (String(this.ttsRuntime.backend || "").toLowerCase() !== "piper") {
      throw new Error("Live voice profile switching is only available for local Piper voices.");
    }

    const profile = typeof profileInput === "string"
      ? resolveVoiceProfile(profileInput, this.voiceProfiles)
      : profileInput;
    if (!profile) {
      throw new Error(`Unknown voice profile. Available profiles: ${this.getAvailableVoiceProfiles()}`);
    }

    if (profile.id === this.ttsRuntime.model) {
      return {
        changed: false,
        profile,
      };
    }

    const nextSpeech = this.createSpeechService({ ttsOverrides: { model: profile.id } });
    let probePath = null;
    try {
      probePath = await nextSpeech.synthesizeToWav("Voice profile ready.");
    } catch (error) {
      nextSpeech.close();
      throw error;
    } finally {
      if (probePath) {
        await fsPromises.rm(probePath, { force: true }).catch(() => {});
      }
    }

    this.speech.close();
    this.speech = nextSpeech;
    this.ttsRuntime.model = profile.id;
    this.voiceProfiles = discoverPiperVoiceProfiles(this.config.voiceTtsDataDir, profile.id);
    await this.persistRuntimeSettings({ voiceProfile: profile.id });
    console.log(`[thomas-discord] Voice profile switched: ${profile.id}`);
    return {
      changed: true,
      profile,
    };
  },

  async setWakeWordRequired(requireWakeWord) {
    const nextValue = Boolean(requireWakeWord);
    const currentValue = this.isVoiceWakeWordRequired();
    if (nextValue === currentValue) {
      return { changed: false, requireWakeWord: currentValue };
    }

    await this.persistRuntimeSettings({ voiceRequireWakeWord: nextValue });
    return { changed: true, requireWakeWord: nextValue };
  },

  async setWakeWords(wakeWords) {
    const normalized = [...new Set(
      (Array.isArray(wakeWords) ? wakeWords : [])
        .map((item) => String(item || "").trim())
        .filter(Boolean),
    )];
    if (normalized.length === 0) {
      throw new Error("Wake word list cannot be empty.");
    }

    await this.persistRuntimeSettings({ voiceWakeWords: normalized });
    return { wakeWords: normalized };
  },

  async setTextMentionMode(requireMention) {
    const nextValue = Boolean(requireMention);
    const currentValue = Boolean(this.getRuntimeSettings().requireMention);
    if (nextValue === currentValue) {
      return { changed: false, requireMention: currentValue };
    }

    await this.persistRuntimeSettings({ requireMention: nextValue });
    return { changed: true, requireMention: nextValue };
  },
};
