### Changed

- **Build reads as a conversation, and you can act on a run while it works (the 2026-10 Build redesign, screens 3a and 4a-4c).** Build wears the Dark look whatever theme Chat uses, with your words and Thomas's in bright prose and the background work as dim one-line rows (Read, Edited `+11 −2`, Ran, Checked), a STEPS card for the lead's plan, the lines an agent is writing as it writes them, the Verifier's proof card, and an ask-the-user card. The composer's button is **Pause** while a run is going, **Resume** after a pause and **Send** as soon as you type; a message you send mid-run waits above the composer with its own **Steer** (into the lead's inbox, read at its next step) and ✕, under one status line ("Step 2 of 5 · 1m 12s"). While Thomas is asking you something, what you type is your answer. **Activity** lists every agent on the run with the files it holds; open one to message it directly in a side chat. The sidebar marks each task running, verified, stopped or needing attention, and the header names the project, its branch and the task. A run led by Claude Code cannot hold mid-step or take messages, so for it the button stays **Stop** and the side chat says why.

### Added

- **Run controls behind it:** `POST /api/evolve/agent/{pause,resume,message,answer}`, `GET /api/evolve/agent/messages` and `GET /api/evolve/agent/live-diff`; every run event now carries its time (`ts`) and file tools their `path` and `+/−` counts; the Build lead has `plan.update` and `ask.user`; `/send` and `/status` say what the run's lead can take (`controls`), and the conversation list says how each task's newest run ended (`last_outcome`).

### Removed

- The steer box inside the transcript (the queued message's Steer replaces it), the sticky action line at the top of the transcript (its words are the status line above the composer), and the browser shell's Ask Thomas pill with the quick chat only it opened.
