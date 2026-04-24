Option Explicit

Dim shell
Dim fso
Dim appDir
Dim command
Dim venvPython
Dim setupMarker

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
venvPython = appDir & "\.venv\Scripts\python.exe"
setupMarker = appDir & "\runtime\setup\last_setup.txt"

If (Not fso.FileExists(venvPython)) Or (Not fso.FileExists(setupMarker)) Then
  command = "cmd /c """ & appDir & "\scripts\first-run.cmd"" -ConfirmedInstallChanges"
  ' First-run setup must be visible so dependency or Python failures are understandable.
  shell.Run command, 1, False
Else
  command = "powershell -NoProfile -ExecutionPolicy Bypass -File """ & appDir & "\scripts\run-ui.ps1"" -ConfirmedInstallChanges -NoPrompt -NoTray"
  ' After setup, run hidden so consumer launches feel app-like, not terminal-driven.
  shell.Run command, 0, False
End If
