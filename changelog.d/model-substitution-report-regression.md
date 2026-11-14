### Fixed

- Strengthened `test_the_report_says_the_model_was_substituted_not_applied` to check that the historical reroute report consistently names `claude:sonnet` as the effective model and explains both the requested model and its replacement. The historical fixture preserves rejection of unsupported models in new requests.
