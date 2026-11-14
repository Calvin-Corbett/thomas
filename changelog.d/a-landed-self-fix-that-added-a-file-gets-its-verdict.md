### Fixed

- A self-fix that landed just before the promoter stopped now gets its landed verdict even when it added or deleted a file, on a single card or a shared one. It used to be refused as "no longer applies to dev", and its team sent to repair work that was already in; nearly every self-fix adds a changelog.d file. A change that never landed, with a file in its way, is still refused.
