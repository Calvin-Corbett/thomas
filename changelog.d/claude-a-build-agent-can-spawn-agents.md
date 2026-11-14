### Added

- **The Build agent can hand work to other agents, and you watch them do it.** `task.spawn` gives the lead a way to delegate one self-contained piece of a task — a page, a file, a build and its tests — to an agent of its own, and returns that agent's result to the lead. The worker had no spawn capability at all before this, so a big task was always one long sequence.
- **Every spawned agent appears in the Build activity panel.** The panel renders the Build session's transcript, so a child's steps are written into that same transcript with the child's name on them: `Used Draft home page > fs.write_file` sits beside the lead's own steps in one interleaved story rather than happening invisibly.

### Changed

- **A spawned agent cannot spawn.** The child runs the same worker with `can_spawn=False`, so the recursion is one level deep by construction rather than by a counter somebody has to remember to check.
- **A helper that falls over is a result, not a casualty.** A failed child is recorded on the session and returned to the lead, which decides what to do next; it never ends the run.
