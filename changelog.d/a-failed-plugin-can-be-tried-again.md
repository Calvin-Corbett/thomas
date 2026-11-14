### Fixed

- **A plugin that failed while Thomas started can now be tried again.** Turning it on used to do nothing, because the failed plugin was still sitting in its place, so a Try again button would have looked broken. It now clears that away first, letting anything still running finish, and starts afresh. The list of plugins also says why one failed when it failed after loading, which used to come back blank.
- **Turning a plugin on while it is still stopping is refused.** It used to save the plugin as on while it finished going off, so what you saw and what came back at the next restart disagreed.
- **A late Stop now leaves a running plugin alone.** Pressing it after the wait was over, from another tab say, used to start a stop of its own and cut whatever the plugin was doing. Pressed in time, it now also reaches work in anything using that plugin, which a stop waits for first and which it used to miss.

### Added

- **Each plugin now carries its own plain description.** Every plugin has a name, what it does, what stops while it is off, and what Stop now would cost, written for you rather than in internal names. Saved-choice and plugin-list problems also carry fixed codes beside their text. Nothing you can see changes yet: this is what the Plugins page will read.
