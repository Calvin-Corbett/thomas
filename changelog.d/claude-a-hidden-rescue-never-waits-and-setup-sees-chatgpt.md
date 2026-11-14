### Fixed

- When Thomas fails to start, the Boot Doctor rescue it runs in a hidden window no longer stops at "Press Enter to close this window" and waits there for good; `run-ui.ps1` now starts it with `--no-interactive`.
- Easy Setup now sees a connected ChatGPT sign-in. Its check passed `python -c` a script with double quotes, which Windows PowerShell 5.1 strips, so the check always failed.
