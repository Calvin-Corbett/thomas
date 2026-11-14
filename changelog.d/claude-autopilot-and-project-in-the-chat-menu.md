### Fixed

- **Autopilot and "This project" can be chosen from Chat.** The AI-settings menu hardcoded its own autonomy list, stopping at Full autonomy, so the Autopilot level added to the backend could not be picked from the UI at all. And "This project" was filtered to Code and Work modes, so in Chat — where you ask Thomas to fix himself — the one file-access level that lets him reach his own repo was hidden, and the explicit "Thomas's own space" it sent overrode the configured level.
