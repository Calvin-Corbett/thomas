### Fixed
- Your local project list retains complete saved-project cards and generated deliverables while its catalogue refreshes in the background, and includes new imports without waiting for the scan.
- Your Thomas project list retains its last complete project cards while a slow scan refreshes states, changed files, and unreadable-project warnings; a cold list has a bounded wait. A project started during or after a scan triggers a fresh listing, and a failed scan cannot masquerade as a complete empty list.
- Project pickers retry a refreshing list to show newly discovered projects and deliverables.
- The Library checks a background catalogue refresh and rerenders through its existing Refresh control when the complete list becomes available.
