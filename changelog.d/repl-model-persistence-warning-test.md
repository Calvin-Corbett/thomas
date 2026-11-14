### Fixed
- The REPL model-persistence warning smoke test now injects a stub at `thomas.preferences.model_prefs`, the module the REPL imports, instead of an obsolete server module. The stub raises without importing the preferences store; the test checks the persistence arguments and the warning's profile, model, and exception.
