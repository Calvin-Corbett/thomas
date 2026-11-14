### Fixed
- ChatGPT/Codex HTTP 401 drops a rejected stored copy in the running server's secret store, consults the local Codex login when no newer token is stored, and retries with a different token at most once; if that newer token is also rejected, the live login is checked and a usable replacement is imported for the next call without another retry.
- Chat distinguishes a rejected stored token from a rejected live Codex login, reports whether the provider response says revoked, expired, or rejected, and suggests `codex login` when the checked live token was rejected or its refresh returned HTTP 401.
- Build treats provider HTTP 401 as terminal and retains the reason in its child report instead of backing off indefinitely; other model errors remain retryable.
