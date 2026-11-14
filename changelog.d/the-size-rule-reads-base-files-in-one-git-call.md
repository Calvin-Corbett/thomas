### Changed

- **Checking a change against the file-size rule now asks git once, not once per file.** Thomas started about 100 git processes a minute, and the size rule ran one `git show` for every measured file, twice for every hand-in; each is a whole process start on Windows. It now reads every measured file's earlier version with a single `git cat-file --batch`, which gives exactly what `git show` gave, and falls back to one file at a time if git cannot answer that way.
