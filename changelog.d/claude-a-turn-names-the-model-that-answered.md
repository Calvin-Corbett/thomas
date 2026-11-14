### Fixed

- A Build turn now records the exact model its engine reported running, next to the name the run asked for. Before, a turn stored only the request, such as `claude:opus`. The reports that name the exact model were thrown away: Claude Code's `init` event and its result's `modelUsage`, and on GPT the `response.model` the ChatGPT/Codex stream sends. So a finished run could be labelled Opus with nothing anywhere able to say which Opus produced it.
  - The exact id is now written into the run transcript as it arrives, from Claude Code's stream and from the provider's own report on the GPT loop. That report is the Codex stream's `response.model`, a chat-completions chunk's `model`, or Anthropic's `message_start`.
  - When the run ends, the id is read back onto the turn as `model_used`.
  - The Build view shows it as a "Ran on claude-opus-5-5" status line, both live and when the conversation is reopened. In the Code view that row is headed "Model that answered", not "Workspace update".
  - Each Build turn's header in the Code view names the exact model, and hovering shows the name it asked for.
  - A turn with no report says so rather than looking complete. The header reads "claude:opus · model not reported", and the Build conversation list reads "Opus (model not reported)". That covers a turn recorded before this change and a run whose engine never named its model.
  - The conversation list's `last_model_used` comes from the same turn as `last_model`, so it never pairs one run's request with another run's model.

- The Claude model menu no longer calls `opus` "Claude Opus (newest)". Nothing had checked that label. The CLI resolves those names itself, and on Claude Code 2.1.278 `--model opus` starts `claude-opus-5` while `claude-opus-5-5` exists.
  - A label now repeats only what has been checked: the model the engine reported starting for that name here, or nothing.
  - Only the `init` event teaches it. `modelUsage` also lists helper models a run called, and one run that used `claude-haiku-4-5-20251001` beside `claude-opus-5-5` would otherwise have made the menu say `opus` started Haiku. The Build runner and the server share one file for what they have learned, and the server checks that file before it saves, so a wrong value left there cannot come back after a restart.
  - Anthropic's own list is kept as a separate fact with separate wording. "The newest Opus Anthropic lists" and "the model `opus` starts" are different questions, and this is exactly where they disagreed. When choosing the newest id from that list, the version outranks the release date, so `claude-sonnet-4-5-20250929` is ranked above `claude-sonnet-4-20250514`.
  - The picker labels the `opus`, `sonnet` and `haiku` rows from what is known each time it asks for the model list, not from the cached list. A recorded turn therefore changes the menu the next time the picker asks, without waiting for the list's next refresh.

  You asked for this in these words: "never label an alias with a claim you have not checked". Verified with a real Build run on 2026-09-25, through the same runner and recorder the server uses. The run asked Claude Code 2.1.282 for `opus`, the engine reported `claude-opus-5-5`, and the recorded turn says `model: claude:opus`, `model_used: claude-opus-5-5`.
