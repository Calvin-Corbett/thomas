### Added

- **Settings has a Plugins section, where you can turn parts of Thomas off and on.** Each plugin shows what it does, what stops while it is off, and what it is doing right now. A switch acts as soon as you press it, with no Save button, and the page shows what Thomas reports back rather than assuming the press worked. If a stop has to wait for running work, the row says what it is waiting for and offers Stop now with its cost printed beside it. If a plugin did not start, the row gives the reason, with Try again, Leave it off and Ask Thomas why. If Thomas stops answering, the rows dim and lock until it is back. You can open the section directly at `/settings?embed=1&section=plugins`.

### Removed

- **Plugin Directory and Auto-load Plugins are gone from Settings > Advanced.** Nothing in Thomas read either of them, so changing them did nothing. Searching Settings for "plugin" now opens the new section.
