### Fixed

- **A test no longer fails because of the test that ran before it.** Two tests left `AGENT_ID` and `AGENT_SESSION_ID` set, only `THOMAS_` keys were put back afterwards, and 69 tests then failed in a full run while passing alone, on a commit from before the plugin work as well as after it. Those keys are put back now. Two translator tests also expect the `source` and `provider_text` fields that a 10-27 change added on purpose.
- **A launcher test no longer fails for running late.** Its "a start began five minutes ago" was dated when the test file was imported, so more than 25 minutes into a full run the launcher's 30-minute limit made that start look old and the test failed, in every long run. The start is now dated as the launcher runs.
