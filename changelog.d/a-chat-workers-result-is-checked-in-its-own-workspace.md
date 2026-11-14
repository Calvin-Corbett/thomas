### Fixed

- When you hand Chat a background task, its result is now checked in the task's own workspace. Before, a file the task wrote could read as missing while a file of the same name in Thomas's working folder could pass for work the task never did. Thomas's fixes to itself are now checked in their own private copy as well.
- For a task with no shell, the file-size check now uses the guard that ships with Thomas, pointed at the task's folder. Before, it ran whichever guard script it found in that folder, including one the task could have written.
