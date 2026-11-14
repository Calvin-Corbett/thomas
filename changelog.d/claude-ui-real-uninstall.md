### Added

- **Uninstall a workspace from its sidebar row.** The "⋯" on a workspace you installed from Marketplace (or a right-click on it) now has Uninstall. It removes the plugin from Thomas, closes its open tabs, and a line under the list says what happened. A workspace that is built into Thomas says so and offers Hide from list instead; "Remove from list" is gone, because it promised a removal it did not do.
- **An uninstalled plugin can always be installed again.** Uninstall keeps a copy of the plugin, and Marketplace lists it with Install. Before this, a plugin imported from a file, or one whose folder was no longer shipped with Thomas, had no other copy: uninstalling it was permanent and Marketplace stopped showing it. Two of the three workspaces installed here today were in that position.

### Fixed

- **Uninstalling or updating Paper Trading no longer deletes what you saved in it.** Its state, saved keys and simulated positions were kept inside the folder that install, update and uninstall delete. They are kept in a separate folder now, and anything still in the old place is moved there before that folder is touched. Life Manager's state gets the same treatment. If the move fails, the uninstall stops and says so, and nothing is removed.
- **The "⋯" on a sidebar row opens its menu.** Since the evening of 9 November it opened the workspace instead, so the menu could only be reached by right-click.

Not changed: the six workspaces built into Thomas (System, Virtual Office, Library, Channels, Token Economy, Marketplace) can be hidden but not uninstalled. They are not downloads, so there is nothing to take away or fetch again.

You said: "I also still can't remove workspaces. It says remove from list, but I actually want to remove like the entire thing ... I want to undo it ... Save the data ... so I can re-download it and keep all my data."
