# Install Thomas On Windows

Use the Windows installer from GitHub Releases. Do not use the GitHub source ZIP unless
you are a developer who wants to read or modify the code.

## Normal Install

1. Download `ThomasSetup_0.14.64.exe` from the latest release:
   <https://github.com/Calvin-Corbett/thomas/releases/latest>
2. Double-click the downloaded `.exe`.
3. Keep **Finish setup and launch Thomas now** checked.
4. Wait for the first-run setup window to finish.
5. Complete Easy Setup when the browser opens.

Thomas should open at `http://127.0.0.1:8899/`. That address means Thomas is
running on your own computer, not on a public internet address.

The installer includes a bundled Windows dependency wheelhouse so first-run
setup should not need to download Python packages from PyPI. If Python itself is
missing, Thomas may still offer to install Python 3.12 through `winget`.

## If Windows Or Security Software Warns You

Thomas starts a local Python web server so your browser can use the app. If a
firewall prompt appears, it should be for local access to `127.0.0.1:8899`.
Thomas does not configure router port forwarding during normal install.

If the installer is unsigned, Windows SmartScreen may show a warning. The
project release workflow supports trusted code signing, but signing requires a
real code-signing certificate configured by the maintainer.

## If Install Fails

Run these files from the Thomas install folder:

- `repair.cmd` to retry the setup path.
- `bootdoctor.cmd` to check startup state.
- `support.cmd` to create a redacted support ZIP under `runtime\support\`.

When first-run setup fails, Thomas also tries to create that support ZIP
automatically before the setup window closes.

Then open an install issue and attach the support ZIP:
<https://github.com/Calvin-Corbett/thomas/issues/new?template=install_failure.yml>

## Developer Install

Only use the source ZIP or `git clone` if you are developing Thomas. Normal users
should use the `.exe` installer because it includes the first-run setup path,
desktop shortcuts, repair tools, and the tested release workflow.
