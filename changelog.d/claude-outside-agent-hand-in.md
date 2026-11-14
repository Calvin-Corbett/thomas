### Added

- **One command hands an outside agent's commits to Thomas's own hand-in.** `python scripts/crew/hand_in_outside.py --clone <path> --base <sha> --tip <sha>` squashes the range into one change, checks it against the current dev, and prints what would be handed in; it writes into the inbox only with `--drop` and `--accept-card-wording`, because the card text a hand-in gets today says it was made in green and checked, which is not true of an outside change. The clone is treated as untrusted: ruff and git run in isolation and every path the change names is checked first.
