### Fixed

- **Task plans are in the repository, so a fresh clone has them.** Fifty-seven task plans
  existed only on one machine, and eleven more carried metadata that disagreed with the
  workboard — the same shape as code that imports a module git never learned about: it
  works for whoever happens to hold the files and fails for everyone else. The plan gate
  reads the committed copy, so it had also begun refusing unrelated commits.
