#define MyAppName "Thomas"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "Thomas"
#define MyAppURL "http://127.0.0.1:8899"
#define MyAppExeName "run-ui.cmd"
#define MyAppLauncherName "launch-thomas.vbs"
#define MyRepairExeName "repair.cmd"

[Setup]
AppId={{A5D9D19E-7CA6-4D8E-9639-1AA6463F9C3A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
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
UninstallDisplayIcon={app}\{#MyAppLauncherName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: ".git\*;.venv\*;node_modules\*;runtime\*;dist\*;pack\*;output\*;logs\*;__pycache__\*;.pytest_cache\*;.mypy_cache\*;.ruff_cache\*;*.pyc;*.pyo;*.zip"

[Icons]
Name: "{group}\Thomas"; Filename: "{app}\{#MyAppLauncherName}"; WorkingDir: "{app}"
Name: "{group}\Thomas (Console)"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Repair Thomas"; Filename: "{app}\{#MyRepairExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall Thomas"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Thomas"; Filename: "{app}\{#MyAppLauncherName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppLauncherName}"; Description: "Launch Thomas now"; Flags: nowait postinstall skipifsilent
