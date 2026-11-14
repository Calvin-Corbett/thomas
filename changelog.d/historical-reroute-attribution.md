### Fixed

- Updated the historical reroute tests in `tests/test_a_run_is_labelled_with_the_model_that_ran.py` to construct past Claude Code settings without submitting an unsupported model as a new request. The tests check model attribution and substitution reporting while retaining rejection coverage for new Qwen and `octopus-7b` requests.
