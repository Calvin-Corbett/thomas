import fsPromises from "node:fs/promises";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import os from "node:os";
import path from "node:path";

import {
  AudioPlayerStatus,
  EndBehaviorType,
  StreamType,
  createAudioResource,
  entersState,
} from "@discordjs/voice";
import ffmpegPath from "ffmpeg-static";
import prism from "prism-media";

import {
  replyLooksClarificationFallback,
  replyLooksInternal,
  sanitizeDiscordReply,
} from "./discord-format.js";
import { getRequiredCapabilityForNativeCommand } from "./discord-access.js";
import { parseNativeCommand } from "./native-commands.js";
import { pcmByteLengthToDurationMs, pcmStereo48kToMono16kWav } from "./voice-audio.js";
import { buildVoiceScopeKey } from "./session-store.js";
import {
  extractWakePhrase,
  formatSpeechText,
  isWakeGreetingPhrase,
  looksLikeSpeechEcho,
  shouldCooldownAfterMissedWake,
} from "./voice-text.js";
import {
  INPUT_BYTES_PER_SAMPLE,
  INPUT_CHANNELS,
  INPUT_SAMPLE_RATE,
  VOICE_BARGE_IN_MIN_MS,
  VOICE_ECHO_WINDOW_MS,
  VOICE_REPEAT_WINDOW_MS,
  buildVoiceDirectRetryPrompt,
  buildVoicePrompt,
  buildVoiceRetryPrompt,
  collectCapturedPcm,
  getVoiceCaptureTimeoutMs,
  prepareSpeechPlaybackText,
  waitForPlayerIdle,
} from "./voice-manager-shared.js";

export const voiceSpeechMethods = {
  async askThomasInVoice({ guildId, speakerName, speakerId, text, speakOptions = undefined }) {
    const state = this.sessions.get(guildId);
    if (!state) {
      throw new Error("Thomas is not connected to a voice channel in this server.");
    }

    const scopeKey = buildVoiceScopeKey({
      guildId: state.guildId,
      channelId: state.voiceChannelId,
    });

    return this.enqueueByScope(scopeKey, async () => {
      let sessionId = await this.sessionStore.getSessionId(scopeKey);
      const prompt = buildVoicePrompt({
        guildName: state.guild.name,
        voiceChannelName: state.voiceChannelName,
        speakerName,
        speakerId,
        transcript: text,
      });

      let result = await this.thomas.sendMessage({
        sessionId,
        prompt,
        apiPath: "/api/v2/chat",
        autonomyLevel: 1,
        tokenEconomy: "cheap",
        reasoningEffort: "low",
        metadata: {
          source: "discord-voice-bridge",
          scope_key: scopeKey,
          guild_id: state.guildId,
          voice_channel_id: state.voiceChannelId,
          speaker_id: speakerId,
        },
      });

      if (replyLooksInternal(result.text)) {
        const retrySessionId = await this.sessionStore.reset(scopeKey);
        result = await this.thomas.sendMessage({
          sessionId: retrySessionId,
          prompt: buildVoiceRetryPrompt(prompt),
          apiPath: "/api/v2/chat",
          autonomyLevel: 1,
          tokenEconomy: "cheap",
          reasoningEffort: "low",
          metadata: {
            source: "discord-voice-bridge",
            scope_key: scopeKey,
            guild_id: state.guildId,
            voice_channel_id: state.voiceChannelId,
            speaker_id: speakerId,
            retried_after_internal_reply: true,
          },
        });

        if (replyLooksInternal(result.text)) {
          await this.sessionStore.reset(scopeKey);
        }
      }

      let replyText = formatSpeechText(
        sanitizeDiscordReply(result.text || "I am here."),
        this.config.voiceMaxReplyChars,
      );

      if (replyLooksClarificationFallback(replyText)) {
        console.warn(
          `[thomas-discord] Voice clarification fallback detected in ${state.voiceChannelName}; resetting session and retrying direct answer`,
        );
        sessionId = await this.sessionStore.reset(scopeKey);
        result = await this.thomas.sendMessage({
          sessionId,
          prompt: buildVoiceDirectRetryPrompt({
            guildName: state.guild.name,
            voiceChannelName: state.voiceChannelName,
            speakerName,
            speakerId,
            transcript: text,
          }),
          apiPath: "/api/v2/chat",
          autonomyLevel: 1,
          tokenEconomy: "cheap",
          reasoningEffort: "low",
          metadata: {
            source: "discord-voice-bridge",
            scope_key: scopeKey,
            guild_id: state.guildId,
            voice_channel_id: state.voiceChannelId,
            speaker_id: speakerId,
            retried_after_clarification_fallback: true,
          },
        });

        replyText = formatSpeechText(
          sanitizeDiscordReply(result.text || ""),
          this.config.voiceMaxReplyChars,
        );

        if (replyLooksClarificationFallback(replyText)) {
          console.warn(
            `[thomas-discord] Voice clarification fallback persisted in ${state.voiceChannelName}; suppressing bad reply`,
          );
          await this.sessionStore.reset(scopeKey);
          replyText = "I heard you, but my voice reply glitched. Ask me again.";
        }
      }

      if (replyText) {
        await this.speakText(state.guildId, replyText, speakOptions);
      }
      return replyText;
    });
  },

  async processVoiceTranscript({ guildId, member = null, userId = "", rawTranscript = "", speakOptions = undefined }) {
    const state = this.sessions.get(guildId);
    if (!state) {
      throw new Error("Thomas is not connected to a voice channel in this server.");
    }

    const resolvedUserId = String(userId || member?.id || "").trim();
    const resolvedMember = member || await state.guild.members.fetch(resolvedUserId).catch(() => null);
    if (!resolvedMember || resolvedMember.user?.bot) {
      return {
        handled: false,
        action: "ignored-member",
        rawTranscript,
        transcript: "",
        replyText: "",
      };
    }

    const transcript = extractWakePhrase(rawTranscript, {
      wakeWords: this.getVoiceWakeWords(),
      requireWakeWord: this.isVoiceWakeWordRequired(),
    });
    if (!transcript) {
      if (rawTranscript) {
        console.log(`[thomas-discord] Voice ignored without wake word in ${state.voiceChannelName}: ${rawTranscript}`);
        if (
          shouldCooldownAfterMissedWake(rawTranscript, {
            wakeWords: this.getVoiceWakeWords(),
            requireWakeWord: this.isVoiceWakeWordRequired(),
          })
        ) {
          const cooldownUntil = Date.now() + this.config.voiceNoWakeCooldownMs;
          state.ignoredUntilByUser.set(resolvedMember.id, cooldownUntil);
          console.log(
            `[thomas-discord] Voice cooldown set in ${state.voiceChannelName}: user=${resolvedMember.id} ms=${this.config.voiceNoWakeCooldownMs}`,
          );
        }
      }
      return {
        handled: false,
        action: "ignored-no-wake-word",
        rawTranscript,
        transcript: "",
        replyText: "",
      };
    }

    state.ignoredUntilByUser.delete(resolvedMember.id);

    if (this.isRecentSpeechEcho(state, transcript)) {
      console.log(`[thomas-discord] Voice suppressed likely echo in ${state.voiceChannelName}: ${transcript}`);
      return {
        handled: false,
        action: "ignored-echo",
        rawTranscript,
        transcript,
        replyText: "",
      };
    }

    if (this.isDuplicateTranscript(state, resolvedMember.id, transcript)) {
      return {
        handled: false,
        action: "ignored-duplicate",
        rawTranscript,
        transcript,
        replyText: "",
      };
    }

    console.log(`[thomas-discord] Voice heard ${resolvedMember.displayName}: ${transcript}`);
    if (isWakeGreetingPhrase(transcript)) {
      await this.speakText(state.guildId, "Yeah?", speakOptions);
      return {
        handled: true,
        action: "wake-greeting",
        rawTranscript,
        transcript,
        replyText: "Yeah?",
      };
    }

    const nativeCommand = parseNativeCommand(transcript);
    if (nativeCommand) {
      const requiredCapability = getRequiredCapabilityForNativeCommand(nativeCommand);
      if (requiredCapability && !this.canUserUseCapability(resolvedMember.id, requiredCapability)) {
        console.log(
          `[thomas-discord] Voice ignored command in ${state.voiceChannelName}: ${resolvedMember.displayName} lacks ${requiredCapability}`,
        );
        return {
          handled: false,
          action: "ignored-capability",
          rawTranscript,
          transcript,
          replyText: "",
        };
      }
      const nativeReplyText = await this.handleNativeVoiceCommand(state, resolvedMember, nativeCommand);
      return {
        handled: true,
        action: `native-${nativeCommand.type}`,
        rawTranscript,
        transcript,
        replyText: typeof nativeReplyText === "string" ? nativeReplyText : "",
      };
    }

    const pendingPlaybackUserId = String(state.pendingPlaybackQueryUserId || "").trim();
    const pendingPlaybackActive =
      pendingPlaybackUserId
      && pendingPlaybackUserId === resolvedMember.id
      && Number(state.pendingPlaybackQueryUntil || 0) > Date.now();
    if (pendingPlaybackActive) {
      if (!this.canUserUseMedia(resolvedMember.id)) {
        state.pendingPlaybackQueryUserId = "";
        state.pendingPlaybackQueryUntil = 0;
        return {
          handled: false,
          action: "ignored-capability",
          rawTranscript,
          transcript,
          replyText: "",
        };
      }
      state.pendingPlaybackQueryUserId = "";
      state.pendingPlaybackQueryUntil = 0;
      const result = await this.playTrack({
        guildId: state.guildId,
        query: transcript,
        requestedBy: resolvedMember.displayName,
        textChannelId: state.textChannelId,
      });
      const replyText = result.queued
        ? `Queued ${this.summarizeTrackForSpeech(result.track)}.`
        : `Playing ${this.summarizeTrackForSpeech(result.track)}.`;
      return {
        handled: true,
        action: "native-play-followup",
        rawTranscript,
        transcript,
        replyText,
      };
    }

    if (!this.canUserTalk(resolvedMember.id)) {
      console.log(`[thomas-discord] Voice ignored prompt in ${state.voiceChannelName}: ${resolvedMember.displayName} lacks talk access`);
      return {
        handled: false,
        action: "ignored-talk-access",
        rawTranscript,
        transcript,
        replyText: "",
      };
    }

    const thomasStartedAt = Date.now();
    const replyText = await this.askThomasInVoice({
      guildId: state.guildId,
      speakerName: resolvedMember.displayName,
      speakerId: resolvedMember.id,
      text: transcript,
      speakOptions,
    });
    console.log(`[thomas-discord] Voice Thomas reply completed in ${Date.now() - thomasStartedAt}ms`);
    return {
      handled: true,
      action: "thomas-reply",
      rawTranscript,
      transcript,
      replyText,
    };
  },

  async speakText(guildId, text, { awaitPlayback = true } = {}) {
    const state = this.sessions.get(guildId);
    if (!state) {
      throw new Error("Thomas is not connected to a voice channel in this server.");
    }

    const preparedSpeech = prepareSpeechPlaybackText(text, this.config.voiceMaxReplyChars);
    if (!preparedSpeech) {
      return;
    }
    const { synthText } = preparedSpeech;

    const now = Date.now();
    if (state.lastSpokenText === synthText && now - state.lastSpokenAt < VOICE_REPEAT_WINDOW_MS) {
      console.log(`[thomas-discord] Voice suppressed duplicate line in ${state.voiceChannelName}: ${synthText}`);
      return;
    }

    state.lastSpokenText = synthText;
    state.lastSpokenAt = now;

    console.log(`[thomas-discord] Voice speaking in ${state.voiceChannelName}: ${synthText}`);
    const wavPath = await this.speech.synthesizeToWav(synthText);
    this.stopPlayer(state, { suppressQueueAdvance: true });
    const ffmpegArgs = ["-hide_banner", "-loglevel", "error", "-i", wavPath];
    ffmpegArgs.push("-ac", "2", "-ar", "48000", "-f", "s16le", "pipe:1");
    const ffmpeg = spawn(ffmpegPath, ffmpegArgs, {
      windowsHide: true,
    });

    const ffmpegDone = new Promise((resolve, reject) => {
      ffmpeg.once("close", (code) => {
        if (code === 0 || code === null) {
          resolve();
          return;
        }
        reject(new Error(`ffmpeg exited with code ${code}`));
      });
      ffmpeg.once("error", reject);
    });

    ffmpeg.stderr.on("data", () => {});

    const resource = createAudioResource(ffmpeg.stdout, {
      inputType: StreamType.Raw,
      inlineVolume: true,
      metadata: { wavPath },
    });
    resource.volume?.setVolume(Math.max(0, state.volumePercent) / 100);

    state.currentPlaybackProcess = ffmpeg;
    state.currentAudioResource = resource;
    state.playbackKind = "speech";
    state.playbackStartedAt = Date.now();
    state.currentTrack = null;
    state.player.play(resource);
    let playbackStarted = false;
    try {
      await entersState(state.player, AudioPlayerStatus.Playing, 15_000);
      playbackStarted = true;
    } catch {}

    const finalizePlayback = async () => {
      try {
        await Promise.all([waitForPlayerIdle(state.player, 90_000), ffmpegDone]);
      } catch (error) {
        if (error?.name !== "AbortError" && error?.code !== "ABORT_ERR") {
          throw error;
        }
        console.warn(`[thomas-discord] Voice playback aborted in ${state.voiceChannelName}: ${error.message}`);
      } finally {
        ffmpeg.kill();
        if (state.currentPlaybackProcess === ffmpeg) {
          state.currentPlaybackProcess = null;
        }
        if (state.playbackKind === "speech") {
          state.playbackKind = null;
          state.playbackStartedAt = 0;
        }
        await fsPromises.rm(wavPath, { force: true }).catch(() => {});
      }
    };

    if (!awaitPlayback) {
      void finalizePlayback().catch((error) => {
        console.warn(`[thomas-discord] Voice playback cleanup failed in ${state.voiceChannelName}: ${error.message}`);
      });
      return {
        ...preparedSpeech,
        playbackStarted,
      };
    }
    await finalizePlayback();
    return {
      ...preparedSpeech,
      playbackStarted,
    };
  },

  async analyzeSpokenText(text, { keepWav = false } = {}) {
    const preparedSpeech = prepareSpeechPlaybackText(text, this.config.voiceMaxReplyChars);
    if (!preparedSpeech) {
      return null;
    }
    const wavPath = await this.speech.synthesizeToWav(preparedSpeech.synthText);
    try {
      const transcript = await this.speech.transcribeWav(wavPath, this.getVoiceTranscriptionOptions());
      return {
        ...preparedSpeech,
        transcript: String(transcript || "").trim(),
        wavPath: keepWav ? wavPath : "",
      };
    } finally {
      if (!keepWav) {
        await fsPromises.rm(wavPath, { force: true }).catch(() => {});
      }
    }
  },

  async handleSpeakingStart(state, userId) {
    const now = Date.now();
    console.log(
      `[thomas-discord] Voice speaking start in ${state.voiceChannelName}: user=${userId} player=${state.player.state.status} kind=${state.playbackKind || "idle"}`,
    );

    if (state.destroyed) {
      console.log(`[thomas-discord] Voice ignored start in ${state.voiceChannelName}: session destroyed`);
      return;
    }

    if (state.listeningUsers.has(userId)) {
      console.log(`[thomas-discord] Voice ignored start in ${state.voiceChannelName}: already listening to ${userId}`);
      return;
    }

    if (userId === this.client.user?.id) {
      console.log(`[thomas-discord] Voice ignored start in ${state.voiceChannelName}: bot user`);
      return;
    }

    if (!this.canUserTalk(userId) && !this.canUserUseMedia(userId)) {
      console.log(`[thomas-discord] Voice ignored start in ${state.voiceChannelName}: no access for ${userId}`);
      return;
    }

    const ignoredUntil = state.ignoredUntilByUser.get(userId) || 0;
    if (ignoredUntil > now) {
      console.log(
        `[thomas-discord] Voice ignored start in ${state.voiceChannelName}: cooldown ${ignoredUntil - now}ms remaining for ${userId}`,
      );
      return;
    }

    if (state.player.state.status !== AudioPlayerStatus.Idle) {
      if (state.playbackKind === "speech") {
        const msSinceSpoken = now - state.lastSpokenAt;
        if (msSinceSpoken < VOICE_BARGE_IN_MIN_MS) {
          console.log(
            `[thomas-discord] Voice ignored start in ${state.voiceChannelName}: bot speech still settling ${msSinceSpoken}ms ago`,
          );
          return;
        }

        console.log(
          `[thomas-discord] Voice interrupting active speech in ${state.voiceChannelName}: user=${userId} after ${msSinceSpoken}ms`,
        );
        this.stopPlayer(state, { suppressQueueAdvance: true });
        state.lastSpokenText = "";
        state.lastSpokenAt = 0;
      } else {
        console.log(
          `[thomas-discord] Voice proceeding while ${state.playbackKind || "unknown"} is playing in ${state.voiceChannelName}`,
        );
      }
    }

    state.listeningUsers.add(userId);
    try {
      const member = await state.guild.members.fetch(userId).catch(() => null);
      if (!member || member.user.bot) {
        return;
      }

      const captureStartedAt = Date.now();
      const capture = await this.captureUserSpeech(state, userId, {
        maxDurationMs: this.isVoiceWakeWordRequired()
          ? Math.min(this.config.voiceMaxSpeechMs, this.config.voiceWakeCaptureMs)
          : this.config.voiceMaxSpeechMs,
      });
      const { pcm, timedOut, hitMaxBytes } = capture;
      if (!pcm.length) {
        return;
      }
      const captureMs = Date.now() - captureStartedAt;

      if (timedOut || hitMaxBytes) {
        console.log(
          `[thomas-discord] Voice ignored incomplete capture in ${state.voiceChannelName}: user=${userId} timed_out=${timedOut} hit_max=${hitMaxBytes} capture=${captureMs}ms`,
        );
        return;
      }

      const durationMs = pcmByteLengthToDurationMs(pcm.length, {
        sampleRate: INPUT_SAMPLE_RATE,
        channels: INPUT_CHANNELS,
      });
      if (durationMs < this.config.voiceMinSpeechMs) {
        console.log(
          `[thomas-discord] Voice ignored short capture in ${state.voiceChannelName}: user=${userId} duration=${Math.round(durationMs)}ms min=${this.config.voiceMinSpeechMs}ms`,
        );
        return;
      }

      const wavPath = path.join(os.tmpdir(), `thomas-voice-in-${randomUUID()}.wav`);
      let rawTranscript = "";
      try {
        await fsPromises.writeFile(wavPath, pcmStereo48kToMono16kWav(pcm));
        const transcribeStartedAt = Date.now();
        rawTranscript = await this.speech.transcribeWav(wavPath, this.getVoiceTranscriptionOptions(state));
        console.log(
          `[thomas-discord] Voice STT completed in ${Date.now() - transcribeStartedAt}ms after ${captureMs}ms capture`,
        );
      } finally {
        await fsPromises.rm(wavPath, { force: true }).catch(() => {});
      }

      if (rawTranscript) {
        console.log(`[thomas-discord] Voice transcribed ${member.displayName}: ${rawTranscript}`);
      }

      await this.processVoiceTranscript({
        guildId: state.guildId,
        member,
        userId,
        rawTranscript,
      });
    } catch (error) {
      console.warn(`[thomas-discord] Voice listen error in ${state.voiceChannelName}: ${error.message}`);
    } finally {
      state.listeningUsers.delete(userId);
    }
  },

  async captureUserSpeech(state, userId, { maxDurationMs = this.config.voiceMaxSpeechMs } = {}) {
    const opusStream = state.connection.receiver.subscribe(userId, {
      end: {
        behavior: EndBehaviorType.AfterSilence,
        duration: this.config.voiceSilenceMs,
      },
    });
    const decoder = new prism.opus.Decoder({
      rate: INPUT_SAMPLE_RATE,
      channels: INPUT_CHANNELS,
      frameSize: 960,
    });

    const maxBytes =
      Math.ceil((maxDurationMs / 1000) * INPUT_SAMPLE_RATE * INPUT_CHANNELS * INPUT_BYTES_PER_SAMPLE);
    const timeoutMs = getVoiceCaptureTimeoutMs({
      maxDurationMs,
      silenceMs: this.config.voiceSilenceMs,
    });
    return collectCapturedPcm({
      opusStream,
      decoder,
      maxBytes,
      timeoutMs,
      includeMetadata: true,
      onTimeout: () => {
        console.warn(
          `[thomas-discord] Voice capture timed out in ${state.voiceChannelName}: user=${userId} after ${timeoutMs}ms`,
        );
      },
    });
  },

  isDuplicateTranscript(state, userId, transcript) {
    const now = Date.now();
    const normalized = String(transcript || "").trim().toLowerCase();
    const previous = state.lastTranscriptByUser.get(userId);

    if (previous && previous.text === normalized && now - previous.ts < 8000) {
      return true;
    }

    state.lastTranscriptByUser.set(userId, {
      text: normalized,
      ts: now,
    });
    return false;
  },

  isRecentSpeechEcho(state, transcript) {
    if (!state.lastSpokenText || !state.lastSpokenAt) {
      return false;
    }

    if (Date.now() - state.lastSpokenAt > VOICE_ECHO_WINDOW_MS) {
      return false;
    }

    return looksLikeSpeechEcho(transcript, state.lastSpokenText);
  },
};
