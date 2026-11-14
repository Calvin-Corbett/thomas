### Fixed

- A denied directory check on one Thomas work copy now produces a project-naming warning and lets readable projects and queued starts continue; an unreadable overall work inventory still blocks starts.
- Skipped-record warnings include their containing folder, so corrupt records with the same filename in different projects each retain their own warning without duplicating warnings for repeated reads.
