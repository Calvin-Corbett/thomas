### Added

- **The model pickers show what your accounts offer today.** Thomas asks each
  connected provider for its current models, starting with the ChatGPT sign-in:
  the list the Codex app shows, with its order, display names and retirement
  notices. On 2026-09-23 that list held three GPT-6 models the pickers could not
  show.
- Anthropic, OpenAI, Gemini, OpenRouter and local servers are read the same way,
  and the Claude CLI's always-newest names stand in without an Anthropic key.
- The catalog merges every provider's answer into one list: a model first seen
  in the last 7 days carries a New tag, and if a provider's check fails, its
  last good list stays shown instead of disappearing.
- The list refreshes itself when Thomas starts, once a day, and on a Check for
  new models request; the pickers always read the already-known list instead
  of waiting on a provider, and a double press only asks once.
- Build runs a new Claude model as soon as Anthropic lists it, not only the
  names its own pattern already knew.
- The Chat model picker now reads this same live list instead of its own
  ChatGPT-only fetch: a Check for new models button next to when it last
  checked, a New tag on a model seen in the last 7 days, a retirement note
  naming the switch-to model when a provider gives one, and a saved model your
  connection stopped offering stays listed as no longer offered instead of
  quietly switching you to something else.

### Fixed

- A cloud connection with no key no longer fills the menu with a public list
  you cannot use (about 390 rows from OpenRouter and DeepInfra); local servers
  still list without one.
- "Checked just now" reflects only the connections you can use, and a failed
  check shows its own error, named by connection.
- Every connection is checked at once, and one failing reader no longer loses
  the others' answers. Only the Check for new models button refreshes; a page
  load never does.
- A local connection without a key (Ollama, LM Studio, or a server on this
  computer) is listed, and a saved model your connection stopped offering
  stays selected across every open Thomas tab.
