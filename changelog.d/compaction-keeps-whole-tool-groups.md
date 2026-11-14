### Fixed
- **Tool exchanges stay together.** Compaction, its heuristic fallback, the history trim and the request cap keep a tool call with its results, so your shortened conversation does not contain a result after its call has been removed.
- **Pinned messages stay out of summaries.** Compaction never summarizes messages it is told to keep; when due, it can summarize the oldest completed exchange instead of leaving the request builder to discard it without a summary.
