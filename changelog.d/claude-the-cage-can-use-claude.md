### Added

- **The caged Thomas can run Build on your Claude plan, through a Claude sign-in of
  its own.** You chose it on a card when your ChatGPT usage limit ran out: "Switch
  Thomas to Claude now", then "Yes, set it up". The caged server (port 8898) found no
  Claude CLI, so its model list said "no Anthropic API key and no Claude CLI on this
  machine".
  - `scripts/cage/enable_cage_claude.ps1`, run at an elevated prompt, first refuses to
    change anything if `C:\ProgramData\ThomasCage`, its `claude` or `bin` folder, or
    anything inside those two, is a junction or link. It then does four things:
    - It copies your `claude.exe` to `C:\ProgramData\ThomasCage\bin`. That folder is
      owned by Administrators, and you and the cage account may only read and run
      what is in it; its permissions are read back. The copy must match your
      `claude.exe` byte for byte and carry Anthropic's valid signature. The script
      prints its version and SHA-256.
    - It puts the sign-in wrapper there as `bin\sign-in.ps1`.
    - It makes `C:\ProgramData\ThomasCage\claude`, the cage's own Claude folder. The
      cage account can change files there, because the CLI refreshes its sign-in in
      that folder.
    - It pins the fence's allow-list again when it changed, and prints every host it
      adds or removes first.
  - The sign-in never runs the Claude CLI against the cage's folder. The cage can
    write in that folder, and the CLI applies settings it finds in its config folder:
    measured, a settings file's `env.BROWSER` made `claude auth login` run a program as
    the person signing in.
    - You run `bin\sign-in.ps1` in a normal window; it refuses to run elevated. It
      signs in to a new folder under your `LOCALAPPDATA\Temp` that only you can reach,
      in a child process: `CLAUDE_CONFIG_DIR` is set only in that process, so your
      window is left unchanged.
    - It then moves `.credentials.json` into the cage's folder, resets its permissions
      to that folder's, and checks from its permissions that the cage account can read
      and change it. It never reads the file's contents. It deletes the temporary
      folder.
    - The setup script asks for this step only when the cage has no sign-in yet.
      Renewing the sign-in later is the same step.
  - When the cage's folder exists, the caged server puts the copied CLI first on `PATH`,
    sets `CLAUDE_CONFIG_DIR` to the folder, and turns the CLI's nonessential traffic
    off. Build's Claude runs, its Claude helpers and the model list all find it there.
    Without the folder nothing changes.
  - The fence now allows `platform.claude.com`, where the CLI refreshes its sign-in.
    - The fence works per host, so the whole host (the Anthropic Console) becomes
      reachable from the cage.
    - This was measured on 2026-09-24 with no real sign-in, through a recording proxy.
      With an expired sign-in, Claude Code 2.1.278 connected to `platform.claude.com`
      and `api.anthropic.com`; with a current one, to `api.anthropic.com` only.
  - Chat is not included: Claude through the CLI is offered only in Build. Chat on
    Claude still needs an Anthropic API key.

### Security

- **The cage's Claude setup checks for links again right before every delete and
  move, not only once at the start.** Both scripts act inside folders under
  `C:\ProgramData\ThomasCage`, and the cage can write `claude\`. Right before each
  delete, move, overwrite and permission reset, `ThomasCage`, the folder and the item
  are checked again for junctions and links, including a dangling one; after the
  sign-in wrapper moves `.credentials.json` in, it checks again before it resets the
  file's permissions.
- **The elevated setup no longer deletes anything in the cage's Claude folder.** It
  used to remove a `settings.json` or `cowork_settings.json` it found there. Code
  running as an administrator now never deletes through a folder the cage can write.
  Your sign-in was never protected by that clean-up; the order of the sign-in steps
  protects it.
- **Both scripts run `icacls` as `C:\Windows\System32\icacls.exe`, never found on
  `PATH`.** A folder every signed-in account can write sits on `PATH` on this machine.
  `pin_folder.ps1`, which the setup uses to pin the allow-list, still finds `icacls`
  and `takeown` on `PATH`.
- **When a rerun of the setup cannot read an item in the cage's folders, it names the
  item and says what to do.** Before, the link check failed with a bare "access
  denied". Now it says which item it cannot read, that nothing was changed, and to move
  the folder aside with `Rename-Item`, which deletes nothing, before running it again;
  moving `claude` aside means signing in again.
