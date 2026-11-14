### Fixed

- **The verification record no longer calls a test run clean when it never finished.** It used to print "Record is clean. You can now commit your changes." whenever no test was counted as failed, even when the test command had timed out or could not start, because it never looked at the command's own result. Today it said exactly that over "Command timed out after 120s". It now says the command did not finish, with its exit code and the likely reasons, and returns a failure; the commit gate already refused such a record, so only the message was untrue.
