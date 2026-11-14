### Fixed

- **A split is not growth, and the growth guard will know it.** CI's commit-growth guard called the REPL split 786 lines of growth because a new file made by moving code looks like a new file. A new file whose non-blank lines are at least 80 percent lines deleted elsewhere in the same commit is a move; the guard's patch is a prepared owner tap because the guard is protected, proven on a copy against a split and against a genuinely new file, and the move case is a strict xfail test until it lands.
