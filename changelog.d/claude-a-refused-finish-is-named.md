### Fixed

- **A finish that Thomas's own checks refused is no longer reported as a provider
  error.** Every error a background worker raised became "provider-native worker
  reported a retryable error", and the chat passed that on as *"the background
  execution hit a retryable provider error"*. On 2026-09-22 three self-fixes ended that
  way while no provider had failed: each one wrote its change and passed its checks, and
  then Thomas's completion gate refused the finish (the acceptance contract had read the
  worker's own reminder as part of the task; fixed in 1b37b1f2). The runner now names a
  refusal as "the worker's finish did not pass Thomas's acceptance checks". A provider's
  own error text still never reaches the chat.
