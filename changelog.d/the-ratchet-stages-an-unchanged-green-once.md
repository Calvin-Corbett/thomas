### Fixed

- The ratchet now stages an unchanged green copy once where adjacent checks staged it up to three times. In `tests/test_a_ratchet_card_gets_a_second_look.py`, staging fell from 121 calls / 41.306 seconds before to 64 calls / 18.755 seconds after, measured with a temporary wrapper around `_stage_everything` in this checkout.
