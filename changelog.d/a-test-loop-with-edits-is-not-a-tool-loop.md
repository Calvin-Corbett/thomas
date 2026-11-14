### Fixed

- A Build team re-running failing tests while it edits code is no longer stopped as a tool loop: successful file mutations reset repeated-failure counts and re-enable disabled calls; unchanged failures still disable the repeated call.
