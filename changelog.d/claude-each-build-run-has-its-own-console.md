### Fixed

- **One stray Ctrl+C no longer stops every Build run at once.** The caged server and every Build run and check it started shared one console, so a console Ctrl+C sent from anywhere in that tree reached all of them. On 2026-09-26, from 00:42 to 01:09, every run the server hosted was stopped with KeyboardInterrupt together, every few minutes. Each Build run, and each test run of the check before your card, now starts on its own hidden console, so a Ctrl+C sent inside one run reaches that run and nothing else.
