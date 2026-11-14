"""Run the launcher's ``Invoke-ExistingServerGate`` against stand-ins, shared by the tests of what it does.

Everything the gate calls is replaced by a function that records the call and answers
from what the case says, so nothing is asked of a server, opened or stopped. ``Case``
runs the gate once and prints one line: ``name|code=..|<plans asked>|opened=..|stopped=..|port=..|said=..``.
"""

from __future__ import annotations

from pathlib import Path

from tests.launcher_powershell_support import RUN_UI, run_functions

PORT = 22001
MOVED = 22002

_PRELUDE = """
$Port = 22001; $Root = 'C:\\Apps\\Thomas'
function Get-LocalThomasVersion { '9.9.9' }
# What the plan says per port (Plans), else for every port (the second argument of Case).
function Get-ExistingServerPlan {
  param($P, $LocalVersion, $LocalRoot, [switch]$ReplaceIt)
  $script:asked += 'port=' + $P + ' version=' + $LocalVersion + ' root=' + $LocalRoot + ' replace=' + $ReplaceIt.IsPresent + ';'
  $what = if ($script:plans.ContainsKey([int]$P)) { $script:plans[[int]$P] } else { $script:action }
  [pscustomobject]@{ Action = $what; Message = 'plan message for ' + $P; Left = $script:left; Degraded = $script:degraded; Other = $script:other }
}
# The recorded port, which ports listen, and which of them answer as Thomas.
function Get-RecordedPort { return [int]$script:moved }
function Test-PortListening { param($P) return ($script:listening -contains [int]$P) }
function Get-ThomasRunningInstance { param($P) if ($script:answering -contains [int]$P) { return [pscustomobject]@{ Version = '9.9.9' } } return $null }
function Start-Process { param($FilePath) $script:opened += $FilePath }
function Stop-ThomasServerOnPort { param($P) $script:stopped += $P; return ($script:stopPorts -contains [int]$P) }
function Case([string]$name, [string]$action, [hashtable]$set = @{}) {
  $script:action = $action; $script:asked = ''; $script:opened = @(); $script:stopped = @(); $script:Port = 22001
  $script:plans = @{}; foreach ($k in $set['Plans'].Keys) { $script:plans[[int]$k] = $set['Plans'][$k] }
  $script:moved = [int]$set['Moved']
  $script:stopPorts = if ($set.ContainsKey('StopPorts')) { @($set['StopPorts']) } elseif ($set['StopWorked']) { @(22001) } else { @() }
  $script:listening = @($set['Listening']); $script:answering = @($set['Answering'])
  foreach ($k in 'Restart', 'Stop', 'NoBrowser', 'Tray') { Set-Variable -Name $k -Value ([bool]$set[$k]) -Scope Script }
  $script:left = [bool]$set['Left']; $script:degraded = [bool]$set['Degraded']; $script:other = [bool]$set['Other']
  Set-Variable -Name DeepLink -Value ([string]$set['DeepLink']) -Scope Script
  $out = @(Invoke-ExistingServerGate -Again:([bool]$set['Again']) 6>&1)
  $code = @($out | Where-Object { $_ -isnot [System.Management.Automation.InformationRecord] }) | Select-Object -Last 1
  $said = ($out | Where-Object { $_ -is [System.Management.Automation.InformationRecord] } | ForEach-Object { [string]$_.MessageData }) -join ' / '
  $name + '|code=' + $(if ($null -eq $code) { 'null' } else { $code }) + '|' + $script:asked + '|opened=' + ($script:opened -join ',') + '|stopped=' + ($script:stopped -join ',') + '|port=' + $Port + '|said=' + $said
}
"""


def gate_cases(cases: str, work: Path) -> dict[str, str]:
    """Each ``Case`` line of *cases* run through the gate, keyed by its name; ``raw`` is everything printed."""
    out = run_functions(RUN_UI, ["Get-ThomasLaunchUrl", "Invoke-ExistingServerGate"], _PRELUDE + cases, work)
    got = {line.split("|", 1)[0]: line for line in out.splitlines() if "|code=" in line}
    got["raw"] = out
    return got
