### Fixed

- You can find a task in the project where you started it, regardless of the folder Thomas starts from, through the durable project-root index written when each task starts, as promised in 0.19.34.
- “What did I ask you to make?” works again through recent work.
- Reading your tasks across projects does not write to project summaries.
- Updating a task from another project updates that project's summary, not the launch folder's.
- Library cards skip walking installed packages when an artifact or preferred entry is known, and can open a file whose name contains a space.
