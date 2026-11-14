### Fixed

- **A Build run no longer freezes on one long line of output.** Thomas read the Build
  agent's output one line at a time with a 64 KB limit. A longer line, such as a long
  reasoning summary or a large tool result, killed the reader silently: nothing emptied
  the pipe any more, the agent stopped at its next write, and the Build tab showed
  "Working" with nothing happening until you stopped it. The reader now takes the output
  in chunks of any length, and a test feeds it a 200 KB line followed by thousands more.
