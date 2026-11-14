### Fixed
- Your green-removal test now waits for both the work and git folders to be deleted before checking that the green is gone. It no longer starts git from inside the work folder while removal is in progress, which could keep Windows from deleting it.
