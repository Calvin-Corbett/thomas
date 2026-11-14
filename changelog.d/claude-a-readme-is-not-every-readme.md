### Fixed

- **Editing one README no longer makes a check run every test that mentions any README.** The check before your card runs the tests that cover what a change touched. For a file that is not Python it chose every test that says the file's name. Thomas's folder holds 50 files called `README.md` and 131 test files say that name, so on 2026-11-10 a change of 28 files was checked with 235 test files on 16 processes for 25 minutes, and 229 of those were there only because the change edited `extensions/README.md`. Eleven such checks used about 124 processor-hours in two days. When several files share a name, a test is now chosen only if it also names the folder the changed one is in. A name only one file has is treated as before.

You said: "do the smartest thing possible that makes the cpu usgae go down somehting has to be very wrong".
