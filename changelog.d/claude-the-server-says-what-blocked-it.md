### Added

- **Thomas's server now says what blocked it.** While ten Builds ran on 2026-11-10, the server's log said "Event loop was blocked" 409 times in one hour, 508 seconds in all, and the server used one to two whole processors. Nothing said which code was responsible. Now, when the server has been stuck for most of a second, it notes which function had it, and adds up the seconds for each one. The list is at `/api/inspect/server`, the most seconds first, beside the other "Look inside the cage" readings. It keeps counts only, in memory, and starts again from nothing at each restart.
