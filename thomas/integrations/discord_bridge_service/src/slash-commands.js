import { SlashCommandBuilder } from "discord.js";

import { buildVoiceProfileChoices } from "./voice-profiles.js";

export function buildSlashCommands(config) {
  const voiceProfileChoices = buildVoiceProfileChoices(config.voiceTtsDataDir, config.voiceTtsModel);

  return [
    new SlashCommandBuilder()
      .setName("thomas")
      .setDescription("Send a message to Thomas")
      .addStringOption((option) =>
        option.setName("message").setDescription("What you want Thomas to do").setRequired(true),
      ),
    new SlashCommandBuilder().setName("reset").setDescription("Reset Thomas context for this DM or channel"),
    new SlashCommandBuilder().setName("status").setDescription("Show bridge status"),
    new SlashCommandBuilder()
      .setName("voice")
      .setDescription("Control Thomas in voice chat")
      .addSubcommand((subcommand) => subcommand.setName("join").setDescription("Join your current voice channel"))
      .addSubcommand((subcommand) => subcommand.setName("leave").setDescription("Leave the active voice channel"))
      .addSubcommand((subcommand) => subcommand.setName("status").setDescription("Show voice connection status"))
      .addSubcommand((subcommand) =>
        subcommand
          .setName("play")
          .setDescription("Play music in voice chat from a YouTube query or link")
          .addStringOption((option) =>
            option.setName("query").setDescription("Song name or YouTube URL").setRequired(true),
          ),
      )
      .addSubcommand((subcommand) =>
        subcommand
          .setName("search")
          .setDescription("Search YouTube and post results in chat")
          .addStringOption((option) =>
            option.setName("query").setDescription("What to search for").setRequired(true),
          ),
      )
      .addSubcommand((subcommand) => subcommand.setName("queue").setDescription("Show the current queue"))
      .addSubcommand((subcommand) => subcommand.setName("pause").setDescription("Pause the current track"))
      .addSubcommand((subcommand) => subcommand.setName("resume").setDescription("Resume the current track"))
      .addSubcommand((subcommand) => subcommand.setName("skip").setDescription("Skip the current track"))
      .addSubcommand((subcommand) => subcommand.setName("stop").setDescription("Stop voice playback"))
      .addSubcommand((subcommand) =>
        subcommand
          .setName("volume")
          .setDescription("Set Thomas voice playback volume")
          .addIntegerOption((option) =>
            option
              .setName("percent")
              .setDescription("Volume from 0 to 200")
              .setMinValue(0)
              .setMaxValue(200)
              .setRequired(true),
          ),
      )
      .addSubcommand((subcommand) =>
        subcommand
          .setName("profile")
          .setDescription("Switch Thomas to a different installed local voice")
          .addStringOption((option) => {
            option.setName("name").setDescription("Voice profile").setRequired(true);
            for (const choice of voiceProfileChoices) {
              option.addChoices(choice);
            }
            return option;
          }),
      )
      .addSubcommand((subcommand) =>
        subcommand
          .setName("wakeword")
          .setDescription("Turn voice wake-word requirement on or off")
          .addBooleanOption((option) =>
            option.setName("enabled").setDescription("Whether wake words are required").setRequired(true),
          ),
      )
      .addSubcommand((subcommand) =>
        subcommand
          .setName("wakewords")
          .setDescription("Set the active voice wake words")
          .addStringOption((option) =>
            option.setName("words").setDescription("Comma-separated wake words").setRequired(true),
          ),
      )
      .addSubcommand((subcommand) =>
        subcommand
          .setName("effect")
          .setDescription("Play a soundboard effect")
          .addStringOption((option) =>
            option
              .setName("name")
              .setDescription("Effect name")
              .setRequired(true)
              .addChoices(
                { name: "bang", value: "bang" },
                { name: "airhorn", value: "airhorn" },
                { name: "rimshot", value: "rimshot" },
              ),
          ),
      )
      .addSubcommand((subcommand) =>
        subcommand
          .setName("say")
          .setDescription("Make Thomas speak a message in voice chat")
          .addStringOption((option) =>
            option.setName("message").setDescription("What Thomas should say").setRequired(true),
          ),
      )
      .addSubcommand((subcommand) =>
        subcommand
          .setName("ask")
          .setDescription("Ask Thomas something and hear the spoken reply")
          .addStringOption((option) =>
            option.setName("message").setDescription("What you want Thomas to answer").setRequired(true),
          ),
      ),
  ].map((command) => command.toJSON());
}
