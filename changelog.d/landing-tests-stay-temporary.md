### Fixed

- Removed the stray `thomas/new.py` test artifact.
- Landing test fixtures clear inherited `GIT_*` settings before building and changing temporary repositories, including the module-scoped keeper template.
- Added a regression that runs the file-creating approval and keeper cases with Git pointed at a disposable checkout, checks that checkout is unchanged, and rejects new files in the working checkout, including recreation of deleted tracked files.
