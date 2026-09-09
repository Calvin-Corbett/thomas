Option Explicit

Dim shell
Dim fso
Dim appDir
Dim command

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
command = "powershell -NoProfile -ExecutionPolicy Bypass -File """ & appDir & "\scripts\run-ui.ps1"""

' Run hidden so consumer launches feel app-like, not terminal-driven.
shell.Run command, 0, False
