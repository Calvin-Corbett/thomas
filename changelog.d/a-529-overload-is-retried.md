### Fixed
- When a model provider answers HTTP 529 because it is overloaded, your request gets another transport attempt, as it does for HTTP 503, instead of failing immediately.
