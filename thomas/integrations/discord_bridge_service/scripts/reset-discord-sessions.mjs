import "dotenv/config";

import { once } from "node:events";

import { ChannelType, Client, Events, GatewayIntentBits } from "discord.js";

import { loadConfig } from "../src/config.js";
import { SessionStore, buildVoiceScopeKey } from "../src/session-store.js";

const config = loadConfig();
const sessionStore = new SessionStore({
  dataDir: config.dataDir,
  sessionPrefix: config.sessionPrefix,
});

const resetScopeKeys = new Set();

for (const channelId of config.autoChannelIds) {
  resetScopeKeys.add(`guild:${config.guildId}:channel:${channelId}`);
}

if (config.guildId && config.defaultVoiceChannelName) {
  const client = new Client({
    intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates],
  });

  const ready = once(client, Events.ClientReady);
  await client.login(config.discordToken);
  await ready;

  try {
    const guild = await client.guilds.fetch(config.guildId);
    const channels = await guild.channels.fetch();
    const voiceChannel = [...channels.values()].find(
      (channel) =>
        channel &&
        channel.type === ChannelType.GuildVoice &&
        channel.name === config.defaultVoiceChannelName,
    );

    if (voiceChannel) {
      resetScopeKeys.add(
        buildVoiceScopeKey({
          guildId: guild.id,
          channelId: voiceChannel.id,
        }),
      );
    }
  } finally {
    client.destroy();
  }
}

for (const scopeKey of resetScopeKeys) {
  const sessionId = await sessionStore.reset(scopeKey);
  console.log(`${scopeKey} -> ${sessionId}`);
}
