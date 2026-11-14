### Fixed

- Keep direct Build teams compatible with the declared Python 3.10 support by using owned tasks and explicit deadlines. Child streams retain their execution context, bounded buffering and event order; cancellation drains child and model-client cleanup before returning.
- Preserve failures raised during child cleanup even after a terminal event, so incomplete cleanup cannot be reported as a successful integration.
