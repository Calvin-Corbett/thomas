### Fixed

- Installing a plugin from a folder now refuses a folder that contains a Windows junction, or any other reparse point, the same way it already refused a symbolic link; before, a junction slipped past that check and the files it pointed at, which could be anywhere on your computer, were copied into the installed plugin, and the refusal now names the junction it found.
