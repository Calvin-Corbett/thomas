### Fixed

- **Two agents writing session presence at the same moment could not both succeed.** Every writer used one fixed temporary file name before the rename, so a second writer failed with a permission error and the claim tool reported "presence gate failed". Each write now uses its own temporary file and retries the rename briefly.
