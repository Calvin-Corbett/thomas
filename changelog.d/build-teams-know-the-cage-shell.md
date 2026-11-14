### Fixed

- Your caged GPT Build teams now see that `shell.exec` uses Windows `cmd.exe`, not bash: separate independent commands, use `&&` for dependent commands, and double-quote arguments that need grouping. The guidance appears only when the caged GPT prompt offers a shell and `check.run`; Claude CLI, uncaged Open, and Fortress prompts keep their existing shell instructions.
