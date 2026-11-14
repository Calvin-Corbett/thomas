### Changed

- **When a change is sent back, it now says why each test failed, not just which.** The findings named the failing tests but never their error, so the agent repairing the change ran those tests again just to read it: a median of 6 test runs every repair round, 1,687 over the conversations looked at, each one a full pytest start on a busy PC. The report every test process already writes holds the error; the send-back now shows each failing test's message and the last lines of its traceback (at most 6,000 characters for all of them together).
