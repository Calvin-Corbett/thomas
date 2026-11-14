### Fixed
- Your presence gate reports stale overlapping agents whose scope hold has expired in `not_live` and names them in its message instead of forwarding them as coordination warnings.
- Presence override audits retain those `not_live` rows beside warnings; briefly lapsed agents remain warnings and still receive coordination notices.
