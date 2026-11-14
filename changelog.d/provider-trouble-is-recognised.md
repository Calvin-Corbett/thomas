### Added
- A provider-trouble classifier distinguishes overloads, server errors, account limits, and sign-in refusals from short rate-limit bursts and local connection failures.
- A per-provider episode tracker can group Build, Autopilot, and Chat failures, close episodes on success or inactivity, reopen recent episodes, and save and load its state through a given JSON file path. Later changes will connect these components to your runs and conversations.
