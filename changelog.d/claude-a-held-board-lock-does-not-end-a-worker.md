### Fixed

- **A board lock that is held too long no longer ends a workboard worker.** The worker's three board wrappers (`_set_task_status_safe`, `_send_message_safe`, `_release_claim_safe`) let a `TimeoutError` from the board lock propagate out of the loop, which the evidence and dispatch lock adoption made possible after 10 seconds of waiting. A timeout is now returned as a failure with its reason, like every other refusal; other errors still propagate.
