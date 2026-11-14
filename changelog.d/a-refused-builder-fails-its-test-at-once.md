### Fixed

- **A Build team that runs out of time now says so.** The reason came back blank, "Team did not complete: ; work and final receipt at ...", because the deadline's error has no text. It now reads `TimeoutError`, as the team's own record already did.
- **One refused builder no longer costs a test worker.** A test of 100 builders kept its data folder inside the project they copy, and background loops left by earlier tests wrote there. Refusing a builder when the project changes under its copy is correct, so that stays. The data folder now sits outside the project, and the test ends with the team's reason instead of waiting 15 minutes to be killed.
- **Mission control's idle test no longer reads other tests' tasks.** Three unfinished tasks from an earlier test counted as active for five minutes, so this test passed or failed by the order tests ran in.
