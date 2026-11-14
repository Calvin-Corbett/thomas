### Fixed

- **Keep your task in view.** A background task's own request and every message you send while it works now survive compaction and trimming, so a long tool batch cannot leave the next model request without the task.
- **Carry the acceptance contract.** Every model call now receives the contract, including an automatic repair; previously only the first call of a run received it, and a repair received none.
- **Keep tool batches together.** A message you send between tool results now waits until the batch's results are stored instead of splitting the exchange.
- **Compact before evidence is dropped.** Compaction now starts against the request's actual budget, including its tool schemas, response reserve, and tighter history cap, before the request builder would drop results.
- **Stop rather than continue blind.** If a request cannot hold this run's own tool results, the run stops with a clear error and records a recoverable outcome instead of continuing without them.
