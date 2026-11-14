### Fixed
- When your model provider is overloaded or returns a server error, Autopilot waits and tries again by itself instead of using your self-continuations or calling repeated failures a stall. The chat says which provider is having trouble and when it will try again; usage-limit pauses keep their existing words.
- After repeated provider trouble, the wait grows up to 30 minutes. If the trouble continues past the retry limit, your chat explains why Thomas needs a message to carry on.
