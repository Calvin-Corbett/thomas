### Fixed

- Isolate the resurrection CLI message tests to their temporary repository by patching the gate's repository root and invoking `main()` through argparse. The tests no longer consult the real checkout's runtime-protection toggle, and still assert the failure status, dead path, death record, reason, and approval command.
- Add a regression assertion that the CLI fixture uses the temporary repository for runtime-protection checks.
