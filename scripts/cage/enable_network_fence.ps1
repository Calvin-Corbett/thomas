# The network fence around the cage account (Project 4b). Run elevated, once.
#
#   1. the proxy must already be listening (the promoter service runs it, as you);
#      a fence with no way out would cut the caged Thomas off from its models
#   2. scripts\cage\egress.allow is pinned as C:\ProgramData\ThomasPins\egress.allow,
#      where only an administrator can change it
#   3. baseline, from the cage account's own side: a direct connection still works,
#      the proxy refuses an unpinned host and connects a pinned one
#   4. a Windows Firewall rule blocks every outbound connection the cage account
#      makes to anything but loopback
#   5. the same probe again: now the direct connection must fail. If the fence does
#      not hold, or a pinned host stops working, the rule and the pin are taken
#      back out, so nothing is left half-done
#   6. the caged server is restarted so its model calls go through the proxy
#
# Rollback: Remove-NetFirewallRule -Group "Thomas cage network fence", and delete
# C:\ProgramData\ThomasPins\egress.allow (both elevated). Your own account is never
# fenced: the rule names only the cage account.

param(
    [string]$RepoRoot = "",
    [string]$AgentUser = "thomas-agent",
    [string]$PinRoot = "C:\ProgramData\ThomasPins",
    [int]$ProxyPort = 8897,
    [string]$StatusFile = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $scriptDir) }
. (Join-Path $scriptDir "pin_folder.ps1")
$group = "Thomas cage network fence"

$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$text, [string]$colour = "Gray") {
    Write-Host $text -ForegroundColor $colour
    $lines.Add($text) | Out-Null
}

function Invoke-Probe([switch]$Fenced) {
    # Exit codes decide, not stderr (see pin_folder.ps1).
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $probeArgs = @((Join-Path $scriptDir "fence_probe.py"))
        if ($Fenced) { $probeArgs += "--fenced" }
        $out = & $script:python @probeArgs 2>$null | Select-Object -Last 1
        return ($out | ConvertFrom-Json)
    }
    finally { $ErrorActionPreference = $previous }
}

function Remove-Fence {
    Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    $pin = Join-Path $PinRoot "egress.allow"
    if (Test-Path -LiteralPath $pin) { Remove-Item -LiteralPath $pin -Force }
}

try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "not elevated"
    }
    $script:python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    $agentSid = (Get-LocalUser -Name $AgentUser).SID.Value

    $client = New-Object Net.Sockets.TcpClient
    try { $client.Connect("127.0.0.1", $ProxyPort) } catch { throw "the egress proxy is not listening on 127.0.0.1:$ProxyPort; start the promoter service first" }
    finally { $client.Close() }
    Say "  proxy listening on 127.0.0.1:$ProxyPort"

    Initialize-PinFolder -PinRoot $PinRoot
    $allow = [System.IO.File]::ReadAllText((Join-Path $scriptDir "egress.allow"))
    $pinPath = Write-PinFile -PinRoot $PinRoot -Name "egress.allow" -Value $allow
    Say "  allowlist pinned: $pinPath"

    $before = Invoke-Probe
    Say ("  before the rule, as the cage account: " + ($before.results | ConvertTo-Json -Compress))
    if ($before.problems.Count -gt 0) {
        Remove-Fence
        throw ("the cage's connections were not as expected before the fence: " + ($before.problems -join "; "))
    }

    Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    # Everything but loopback, IPv4 and IPv6. A block rule outranks every allow rule,
    # so loopback is left out of the addresses rather than allowed separately.
    $remote = @("0.0.0.0-126.255.255.255", "128.0.0.0-255.255.255.255", "::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff")
    New-NetFirewallRule -DisplayName "Thomas cage: no direct connections out" -Group $group `
        -Direction Outbound -Action Block -Profile Any -RemoteAddress $remote `
        -LocalUser "D:(A;;CC;;;$agentSid)" `
        -Description "Blocks the cage account ($AgentUser) from every address but loopback. Its only way out is the owner's proxy on 127.0.0.1:$ProxyPort (scripts/cage/egress_proxy.py)." | Out-Null
    Say "  firewall rule added for $AgentUser ($agentSid)"

    $after = Invoke-Probe -Fenced
    Say ("  after the rule, as the cage account: " + ($after.results | ConvertTo-Json -Compress))
    if ($after.problems.Count -gt 0) {
        Remove-Fence
        throw ("the fence did not hold, so it was taken back out: " + ($after.problems -join "; "))
    }

    if ((Get-ScheduledTask -TaskName ThomasCagedServer -ErrorAction SilentlyContinue).State -eq "Running") {
        Stop-ScheduledTask -TaskName ThomasCagedServer
        Start-ScheduledTask -TaskName ThomasCagedServer
        Say "  caged server restarted to use the proxy"
    }
    Say "RESULT: network fence in place" "Green"
}
catch {
    Say ("RESULT: failed - " + $_.Exception.Message) "Red"
}
finally {
    if ($StatusFile) {
        try { [System.IO.File]::WriteAllText($StatusFile, ($lines -join "`r`n")) } catch { }
    }
}
