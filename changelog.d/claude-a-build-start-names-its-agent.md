### Fixed

- **A Build start that names its agent is recorded.** The Agent choice that landed on 2026-09-25 makes every Build launch write which agent runs it into the Praxis launch journal, and the journal refused any field it did not know. After the next server restart every Build start -- from Build, a Chat hand-off, Autopilot or a Thomas project round -- would have failed with "invalid Praxis launch context". The journal and its restart scan now take the agent; a launch recorded before the choice restores as it did then, and an unknown field is still refused.

- **A Build start never fails on the Anthropic key lookup.** The agent picker's follow-up (34c84745) looks up a saved Anthropic key in the app's secret store every time Build settles its settings. A store that could not answer made every Build start fail with HTTP 500; it now counts as no saved key.
