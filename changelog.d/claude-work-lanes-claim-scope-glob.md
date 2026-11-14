### Fixed
- A task's own name no longer reads as a search pattern when agents check whether
  their work overlaps. Task folders are named like `[WIP][HSK-...] some task`, and
  the brackets were being read as wildcards, so two agents working on completely
  different tasks were told they were in each other's way - and a folder that
  genuinely did sit inside another was reported as unrelated.

### Changed
- Work mode now reaches its lane runtime: the gate-change proposal routes are
  registered and the board fetches them, and the onboarding wizard receives the
  step rail with each reply.
- Three oversized files are recorded in the monolith baseline at their current
  size, with no room to grow. They were already over the limit and invisible,
  because that guard only measures files a change touches.
- The size guard could not read a file containing any non-English character, and
  silently treated it as brand new rather than reporting that it had failed to
  measure it. Such a file was reported as having grown by its whole length.
