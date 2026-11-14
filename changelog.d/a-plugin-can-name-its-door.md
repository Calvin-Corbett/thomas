### Added

- **A plugin's manifest can name a door, and a slim proof copy only counts real misses.** `plugin_fence.outsiders` finds everything outside a plugin that reaches behind its door, including a module reached through a package by attribute. A change to a door module is never scoped, and a changelog fragment neither stops a scope nor makes one. The miss detector no longer counts the import system or `importlib.metadata` finding a name, and it records who caused each miss.
