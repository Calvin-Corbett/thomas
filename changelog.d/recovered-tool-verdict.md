### Fixed
- The agent-loop, Claude CLI, and transcript verdicts now use the same tool-name evidence: an unnamed failed call after reads disqualifies a no-change answer, while a clean unnamed result does not.
- The recorder describes a captured failed runner terminal verdict as a completed run with an engine failure, including when the runner exits 1; a missing terminal verdict still reports a crash.
