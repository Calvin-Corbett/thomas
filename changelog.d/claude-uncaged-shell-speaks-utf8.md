### Fixed

- **With the cage off, the shell prints non-ASCII.** `shell.exec` without the cage
  ran Python children that wrote cp1252 into a pipe Thomas reads as UTF-8. "é" came
  back as a replacement character, and "→" killed the command. The shell now asks
  for UTF-8, as the caged runner already did.
