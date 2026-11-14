### Fixed

- **The check before a card waits its turn in the same line as the Builds' own test runs.** On 2026-11-13 a check's sixteen test processes ran beside thirteen Builds' test runs on a PC at its limit; its tests timed out and it ended "unavailable" after 92 minutes, twice. Each part of a check now takes a place in the one line, so together they keep the PC under 90%, and the wait is not taken out of the part's own time.
