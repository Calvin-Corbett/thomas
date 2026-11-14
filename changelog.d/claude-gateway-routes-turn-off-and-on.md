### Changed

- **The gateway for other programs can now be turned off and on from the Plugins page.** Its 28 addresses (restart, saved state, the log filter, the OpenAI-style and Responses endpoints, and the policy report) stop answering while it is off. The check of the gateway token is installed by the server itself, so a server set to check every address still refuses a caller who shows no token while this is off, and the gateway will not start if that check is missing.
