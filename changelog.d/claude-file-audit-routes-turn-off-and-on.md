### Changed

- **The two file change record routes can now be turned off and on from the Plugins page.** Turning them off removes only `/api/audit/files` and `/api/audit/runs/{run_id}/files`; the record Thomas keeps of the files a run writes is not touched. Nothing in Thomas reads these routes, and they answer with an empty list today.
