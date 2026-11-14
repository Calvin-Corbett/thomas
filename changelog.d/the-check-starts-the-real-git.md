### Changed

- **The check before your card starts git without the launcher Git for Windows puts in front of it.** `git` on your PATH is `Git\cmd\git.exe`, which only starts `Git\mingw64\bin\git.exe` as a second process and waits for it, so every git a test started was two processes. The tests now find that same git first, from the same install, and a hook or alias it runs still sees the folders the launcher gave it. Anywhere without that launcher in front, or with `MSYSTEM` already set, nothing changes.
