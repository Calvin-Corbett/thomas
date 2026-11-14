### Fixed

- **Each of your task records now has one writer at a time.** When two parts of Thomas updated the same task record at the same moment, the second write could erase what the first had just saved; on 2026-09-11 that lost a field in 5 of 5 tries. A writer whose copy has gone out of date is now stopped instead of overwriting newer work.
- **Updating one task no longer re-reads every task record.** With 1,000 records, one update read 1,001 files and took about 190 ms to refresh the task summary you see; it now reads at most 3.
- **Deleting a chat's tasks no longer blanks a record it cannot remove.** It stops and leaves that record as it was.
- **You can stop a task while its contract checks run.** Contract evaluation no longer holds the task record's write lock; the evaluated evidence is saved against the latest record after the checks finish.
