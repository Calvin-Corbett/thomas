### Changed

- **One plugin can now call another by a name the kernel holds, and neither imports the other.** A worker getting its tools, chat following a handed-in change and the park loop ticking the project queue each used an import that pulled in nearly the whole server, so a plugin that only touched one of them could not be proven alone. Files reaching most of the repo fell from 153 to 62, and seven more plugins now need 648 to 812 files instead of about 1,240. Nothing changes for you: a call with no provider fails naming what is missing, and a server will not start with one missing.
