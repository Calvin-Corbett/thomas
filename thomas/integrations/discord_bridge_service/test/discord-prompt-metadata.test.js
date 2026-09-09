import test from "node:test";
import assert from "node:assert/strict";

import { buildDiscordPromptMetadata } from "../src/discord-prompt-metadata.js";

test("buildDiscordPromptMetadata includes Discord auth and context fields", () => {
  assert.deepEqual(
    buildDiscordPromptMetadata({
      userId: "123",
      displayName: "War Machine Pro",
      guildId: "456",
      channelId: "789",
      scopeKey: "guild:456:channel:789",
      grantedCapabilities: ["talk", "media", "talk"],
      isOwner: true,
      ownerAuthorizedForSettingsActions: true,
      ownerOnlyMode: true,
      slashCommand: "thomas",
      requestKind: "slash_command",
    }),
    {
      source: "discord-bridge",
      scope_key: "guild:456:channel:789",
      discord: {
        user_id: "123",
        display_name: "War Machine Pro",
        guild_id: "456",
        channel_id: "789",
        owner: true,
        owner_only_mode: true,
        granted_capabilities: ["talk", "media"],
        surface: "discord",
        client: "discord_bot",
        slash_command: "thomas",
        request_kind: "slash_command",
        owner_authorized_for_settings_actions: true,
      },
    },
  );
});

test("buildDiscordPromptMetadata normalizes missing values for direct messages", () => {
  assert.deepEqual(
    buildDiscordPromptMetadata({
      userId: " 123 ",
      displayName: "  ",
      scopeKey: "dm:123",
      grantedCapabilities: null,
    }),
    {
      source: "discord-bridge",
      scope_key: "dm:123",
      discord: {
        user_id: "123",
        display_name: null,
        guild_id: null,
        channel_id: null,
        owner: false,
        owner_only_mode: false,
        granted_capabilities: [],
        surface: "discord",
        client: "discord_bot",
        slash_command: null,
        request_kind: "message",
        owner_authorized_for_settings_actions: false,
      },
    },
  );
});
