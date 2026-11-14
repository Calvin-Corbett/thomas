### Added
- When the server's event loop has not run for 30 seconds, it writes every thread's stack to a `loop-freeze-*.txt` beside its log, once per freeze, so a freeze names the call that caused it instead of being found by elimination.
