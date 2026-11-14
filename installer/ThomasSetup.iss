; Build this with scripts\build_windows_installer.ps1 (build-installer.cmd). That script
; stages the release bundle from git and passes /DMyAppVersion and /DStageDir. Do not
; point Source at the working tree: it holds local state (.venv, runtime, .thomas,
; .env.local) that must never reach someone else's machine.
#if VER < EncodeVer(6, 3, 0, 0)
  #error Inno Setup 6.3 or newer is required (ArchitecturesAllowed=x64compatible).
#endif
#ifndef MyAppVersion
  #error MyAppVersion is not set. Build with scripts\build_windows_installer.ps1.
#endif
#ifndef StageDir
  #error StageDir is not set. Build with scripts\build_windows_installer.ps1.
#endif
#define MyAppName "Thomas"
#define MyAppPublisher "Thomas"
#define MyAppURL "https://github.com/Calvin-Corbett/thomas"
#define MyAppExeName "run-ui.cmd"
#define MyAppLauncherName "launch-thomas.vbs"
#define MyRepairExeName "repair.cmd"

[Setup]
AppId={{A5D9D19E-7CA6-4D8E-9639-1AA6463F9C3A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Thomas
DefaultGroupName=Thomas
DisableProgramGroupPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir=..\dist\installer
OutputBaseFilename=ThomasSetup_{#MyAppVersion}
SetupLogging=yes
UninstallDisplayIcon={app}\assets\thomas.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; StageDir is the release bundle from scripts\package_release.py, so it already holds
; only what a user needs. Excludes is a second net: it is comma-separated (Inno reads
; a semicolon as part of one pattern), and a leading backslash anchors a pattern at the
; top of StageDir (a bare "runtime\*" would also drop any folder named runtime inside
; the product). Nothing reads RELEASE_MANIFEST.json at run time, so it stays out of the
; installed copy; thomas.toml has its own line below.
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "\.git\*,\.venv\*,\.thomas\*,\.claude\*,\node_modules\*,\runtime\*,\dist\*,\output\*,\logs\*,\RELEASE_MANIFEST.json,\thomas.toml,__pycache__\*,*.pyc,*.pyo,*.log,.env,.env.local,.env.thomas.production"
; First-run setup writes the default model you pick into thomas.toml. Installing over an
; existing copy must not put the shipped default back.
Source: "{#StageDir}\thomas.toml"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\Thomas"; Filename: "{app}\{#MyAppLauncherName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\thomas.ico"
Name: "{group}\Thomas (Console)"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\thomas.ico"
Name: "{group}\Repair Thomas"; Filename: "{app}\{#MyRepairExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\thomas.ico"
; The Thomas entry starts the server without a window, so closing the browser leaves it running
; and there is no window to close. These two are its off switch: launch-thomas.vbs turns /stop and
; /restart into run-ui.ps1 -Stop and -Restart and says what happened.
Name: "{group}\Stop Thomas"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#MyAppLauncherName}"" /stop"; WorkingDir: "{app}"; IconFilename: "{app}\assets\thomas.ico"
Name: "{group}\Restart Thomas"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\{#MyAppLauncherName}"" /restart"; WorkingDir: "{app}"; IconFilename: "{app}\assets\thomas.ico"
Name: "{group}\Uninstall Thomas"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Thomas"; Filename: "{app}\{#MyAppLauncherName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\thomas.ico"; Tasks: desktopicon

[UninstallDelete]
; The first launch builds these, so the uninstaller does not know about them and used
; to leave hundreds of MB behind. What Thomas stores for the person using it (runtime,
; .thomas) is not listed on purpose: uninstalling must not delete their chats and settings.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\thomas_ai.egg-info"

[UninstallRun]
; A Thomas started from the Start Menu has no window. Without this an uninstall leaves it
; running from a folder that is about to be deleted, and launch-thomas.vbs /stop goes with the
; files. Hidden, and the exit code is not checked: -Stop exits 3 while a Build run is active,
; and that Thomas is then left running (see the guide).
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\scripts\run-ui.ps1"" -Stop"; WorkingDir: "{app}"; Flags: runhidden skipifdoesntexist; RunOnceId: "StopThomasServer"

[Run]
; launch-thomas.vbs is not an .exe or .com file, so Inno needs shellexec to hand it to
; Windows Script Host. Without it the finish page's "Launch Thomas now" box, ticked by
; default, ends in an error dialog. The first launch runs scripts\setup.ps1 without
; automatic tool installs (run-ui.ps1 adds them only on -InstallTools or
; THOMAS_AUTO_INSTALL_TOOLS=1; see Invoke-FirstRunQuickSetup in scripts\run-ui.ps1), so the
; label names only the dependency download. Keep it in step with that script.
Filename: "{app}\{#MyAppLauncherName}"; Description: "Launch Thomas now (the first launch downloads dependencies)"; Flags: shellexec nowait postinstall skipifsilent
