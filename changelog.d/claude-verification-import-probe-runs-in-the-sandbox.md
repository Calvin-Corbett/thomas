### Changed

- **The import check after an edit now follows your cage setting.** When an edit is inside a project folder, the check that imports the edited module goes through the sandbox: caged when the cage is on and answering, here when it is off, and reported as "did not run" (never as a pass) when the cage is required and not answering.
