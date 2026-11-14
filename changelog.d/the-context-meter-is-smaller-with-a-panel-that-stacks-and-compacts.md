### Changed

- **The context meter is half the size and shows what is used.** You said it was too big, should change colour as it fills, and should say the amount used, not what is left. It is now a small bar with just the number ("36%"). The bar and the number run from green through amber to red as the window fills.
- **Click the meter for where the tokens went, and to compact.** A panel opens under the Steps card (the top right column stacks, so more panels can open there too). It shows how many tokens are used of the window, a bar with a mark at 75% where Thomas compacts by himself, and a breakdown: the system prompt, the tool definitions, your messages, Thomas's replies, and the results of each tool he used, each with its tokens and share. The breakdown is measured from the very request Thomas sends each step. **Compact now** asks the running lead to compact at its next step, even below 75%, and the bar drops once it has; it is only available while Thomas is working, and only for Thomas's own loop (Claude Code runs as one process that cannot be reached mid-step). Thomas needs a restart for the breakdown and the Compact action to start working.

### Fixed

- **A green tick on a finished task goes away once you open it.** You said the ticks in the task list act like notifications. A finished task keeps its tick until you open it, then the tick clears; a newer run in the same task brings it back. Red for "needs attention" stays until it is fixed, and the dot for a task that is working is unchanged.
