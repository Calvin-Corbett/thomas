### Changed

- **After a change, Thomas re-downloads only the files that changed.** You said yes to giving each file its own version. Before, one change made the page fetch about 110 files again (3.4 to 5.2 seconds measured with nothing cached, against 0.6 seconds with everything cached). Each script and stylesheet on the chat page now has a version taken from its own contents, so a change to one file moves only that file's address. The window's title bar, tabs and bookmarks scripts follow the same rule.
