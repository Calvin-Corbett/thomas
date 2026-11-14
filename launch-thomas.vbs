Option Explicit

Dim shell
Dim fso
Dim appDir
Dim logDir
Dim logPath
Dim command
Dim exitCode
Dim saved
Dim flag

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
logDir = appDir & "\runtime\logs"
logPath = ""

' "/stop" and "/restart" (a Start Menu entry can pass either) reach run-ui.ps1 as -Stop and -Restart.
flag = ""
If WScript.Arguments.Count > 0 Then
  If LCase(WScript.Arguments(0)) = "/stop" Then flag = " -Stop"
  If LCase(WScript.Arguments(0)) = "/restart" Then flag = " -Restart"
End If

' This script runs in the background, and a box it opens is otherwise often put behind the window
' that just took focus: with MB_SETFOREGROUND it comes to the front. Every dialog goes through Tell.
Const SET_FOREGROUND = 65536
Sub Tell(message, icon)
  MsgBox message, icon + SET_FOREGROUND, "Thomas"
End Sub

' The server runs without a window, so nothing on screen says it is there or ends it. After
' the first launch that worked, say so once, with the command that stops it. runtime\
' remembers that it was said; with nowhere to remember it, nothing is said rather than
' a dialog on every launch.
Sub ExplainBackgroundOnce()
  Dim marker, remembered
  marker = appDir & "\runtime\background-notice-shown"
  If fso.FileExists(marker) Then Exit Sub
  On Error Resume Next
  fso.CreateTextFile(marker, True).Close
  remembered = (Err.Number = 0)
  On Error GoTo 0
  If Not remembered Then Exit Sub
  Tell "Thomas started from this shortcut runs in the background, with no window of its own, so closing the browser does not stop it." & vbCrLf & vbCrLf & _
    "To stop it, press Windows+R and run:" & vbCrLf & "wscript """ & WScript.ScriptFullName & """ /stop", 64
End Sub

' Keep the newest launch logs (the one about to be made included) and delete the rest.
' One still open in a launch that is going on cannot be deleted: it is skipped, does
' not count toward the newest, and the next-oldest goes instead.
Sub PruneLaunchLogs(keep)
  Dim file, oldest, count, stuck, passes
  Set stuck = CreateObject("Scripting.Dictionary")
  On Error Resume Next
  Do
    passes = passes + 1
    If passes > 1000 Then Exit Do
    Set oldest = Nothing
    count = 0
    For Each file In fso.GetFolder(logDir).Files
      If LCase(Left(file.Name, 7)) = "launch-" And LCase(Right(file.Name, 4)) = ".log" And Not stuck.Exists(file.Name) Then
        count = count + 1
        If oldest Is Nothing Then
          Set oldest = file
        ElseIf file.DateLastModified < oldest.DateLastModified Then
          Set oldest = file
        End If
      End If
    Next
    If count < keep Or oldest Is Nothing Then Exit Do
    Err.Clear
    oldest.Delete True
    If Err.Number <> 0 Then stuck.Add oldest.Name, True
  Loop
End Sub

' A hidden window has nowhere to print, so run-ui.ps1's output goes to a file. Each
' launch gets its own: cmd keeps its file open until run-ui.ps1 ends, so a second
' double-click during a slow first launch would fail on a shared name and report a
' failure that never happened.
On Error Resume Next
If Not fso.FolderExists(appDir & "\runtime") Then fso.CreateFolder appDir & "\runtime"
If Not fso.FolderExists(logDir) Then fso.CreateFolder logDir
On Error GoTo 0

command = "powershell -NoProfile -ExecutionPolicy Bypass -File """ & appDir & "\scripts\run-ui.ps1""" & flag
If fso.FolderExists(logDir) Then
  PruneLaunchLogs 5
  Randomize
  logPath = logDir & "\launch-" & Year(Now) & Right("0" & Month(Now), 2) & Right("0" & Day(Now), 2) & "-" & _
    Right("0" & Hour(Now), 2) & Right("0" & Minute(Now), 2) & Right("0" & Second(Now), 2) & "-" & Int(Rnd * 10000) & ".log"
  command = "cmd /c """ & command & " > """ & logPath & """ 2>&1"""
End If

' Run hidden so consumer launches feel app-like, not terminal-driven. Wait for it
' so a launch that fails says so instead of leaving nothing on screen.
exitCode = shell.Run(command, 0, True)
saved = "What it reported could not be saved."
If logPath <> "" Then
  If fso.FileExists(logPath) Then saved = "What it reported is saved in:" & vbCrLf & logPath
End If
If exitCode = 0 Then
  If flag = " -Stop" Then
    Tell "Thomas is stopped.", 64
  ElseIf flag = "" Then
    ExplainBackgroundOnce
  End If
ElseIf exitCode = 3 Then
  Tell "Thomas is in the middle of a Build run, so it was left running." & vbCrLf & vbCrLf & _
    "Wait for the run to finish and try again.", 48
ElseIf exitCode = 4 Then
  ' run-ui.ps1 opened a Thomas that was already running, but it is not the copy that was
  ' launched or is out of date, and it is mid-Build (or would not say), so it was left.
  Tell "Thomas opened the copy that was already running. It is not this copy, or was started before its code" & _
    " changed, and it is in the middle of a Build run (or would not say whether it is), so it was left running." & vbCrLf & vbCrLf & _
    "To replace it once any Build run has finished, run:" & vbCrLf & "wscript """ & WScript.ScriptFullName & """ /restart" & vbCrLf & vbCrLf & _
    saved, 64
ElseIf exitCode = 7 Then
  ' run-ui.ps1 opened the Thomas that was already running (this copy, and current), but its
  ' /api/health says it is degraded, and nothing else on screen would say so.
  Tell "Thomas opened the copy that was already running, but it reports that it is degraded: a part of it is not working." & vbCrLf & vbCrLf & _
    "If you have just repaired Thomas, restart it by running:" & vbCrLf & "wscript """ & WScript.ScriptFullName & """ /restart" & vbCrLf & vbCrLf & _
    saved, 48
ElseIf exitCode = 5 And flag = " -Stop" Then
  ' run-ui.ps1 looked on the port Thomas opens on and on the one it last started on, and found none.
  Tell "No Thomas was found to stop." & vbCrLf & vbCrLf & saved, 64
ElseIf flag = " -Stop" Then
  ' Exit 6: a Thomas is still running after the stop. Any other code: the launcher itself failed.
  Tell "Thomas could not be stopped (exit code " & exitCode & ")." & vbCrLf & vbCrLf & saved, 48
Else
  Tell "Thomas could not start (exit code " & exitCode & ")." & vbCrLf & vbCrLf & _
    saved & vbCrLf & vbCrLf & _
    "If it says Python was not found, install Python 3.10 or newer from python.org and open Thomas again.", 48
End If
