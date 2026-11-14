### Fixed

- **A failed save on the Plugins page stays on screen while the plugin finishes starting.** The page took the plugin arriving for a change that made the warning out of date, so it could say On with nothing saved, and the plugin came back off at the next restart.
- **Keyboard focus goes back to the button it had to leave when Thomas stops answering.** It used to land on the first button left, so pressing Enter after Thomas came back could press Try again on a plugin you had chosen to leave off.
- **Stop now counts only what uses the plugin you pressed it on.** A job in an unrelated plugin that was stopping at the same moment could make the page say a plugin stopped partway when it had nothing running.
