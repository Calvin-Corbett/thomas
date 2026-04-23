[CmdletBinding()]
param(
    [string]$UserName = ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name),
    [switch]$EnableFeatures,
    [switch]$EmitJson,
    [string]$OutputPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-IsAdmin {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-FeatureState([string]$FeatureName) {
    try {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $FeatureName
        return [ordered]@{
            feature = $FeatureName
            state = [string]$feature.State
        }
    } catch {
        return [ordered]@{
            feature = $FeatureName
            state = 'unknown'
            error = $_.Exception.Message
        }
    }
}

function Ensure-LocalGroupMember([string]$GroupName, [string]$MemberName) {
    $members = @(Get-LocalGroupMember -Group $GroupName -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
    if ($members -contains $MemberName) {
        return [ordered]@{ changed = $false; message = "$MemberName already in $GroupName" }
    }
    Add-LocalGroupMember -Group $GroupName -Member $MemberName
    return [ordered]@{ changed = $true; message = "Added $MemberName to $GroupName" }
}

if (-not (Test-IsAdmin)) {
    throw 'This script must be run from an elevated PowerShell session.'
}

$features = @(
    'Microsoft-Hyper-V-All',
    'Microsoft-Hyper-V-Management-PowerShell',
    'Microsoft-Hyper-V-Tools-All'
)

$result = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    requested_user = $UserName
    hyperv_admins_before = @((Get-LocalGroupMember 'Hyper-V Administrators' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name))
    features_before = @($features | ForEach-Object { Get-FeatureState $_ })
    vmconnect_exists = Test-Path (Join-Path $env:WINDIR 'System32\vmconnect.exe')
    group_change = $null
    enabled_features = @()
    restart_required = $false
    relog_required = $false
    notes = @()
}

$result.group_change = Ensure-LocalGroupMember -GroupName 'Hyper-V Administrators' -MemberName $UserName
if ($result.group_change.changed) {
    $result.relog_required = $true
    $result.notes += 'Sign out and back in after group membership changes so the new token can manage Hyper-V.'
}

if ($EnableFeatures) {
    foreach ($name in $features) {
        $state = ($result.features_before | Where-Object { $_.feature -eq $name } | Select-Object -First 1).state
        if ($state -ne 'Enabled') {
            $enable = Enable-WindowsOptionalFeature -Online -FeatureName $name -All -NoRestart
            $result.enabled_features += [ordered]@{
                feature = $name
                restart_needed = [bool]$enable.RestartNeeded
                state = [string]$enable.State
            }
            if ($enable.RestartNeeded) {
                $result.restart_required = $true
            }
        }
    }
    if ($result.restart_required) {
        $result.notes += 'Restart the machine before trying to manage Thomas worker VMs.'
    }
} else {
    $missing = @($result.features_before | Where-Object { $_.state -ne 'Enabled' } | ForEach-Object { $_.feature })
    if ($missing.Count -gt 0) {
        $result.notes += ('Run this script again with -EnableFeatures to turn on: ' + ($missing -join ', '))
    }
}

$result.hyperv_admins_after = @((Get-LocalGroupMember 'Hyper-V Administrators' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name))
$result.features_after = @($features | ForEach-Object { Get-FeatureState $_ })
$result.hyperv_cmdlets = @((Get-Command Get-VM,Start-VM,Restore-VMSnapshot,Checkpoint-VM -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name))
$result.ready_for_thomas_vm = [bool](
    ($result.hyperv_admins_after -contains $UserName) -and
    (@($result.features_after | Where-Object { $_.state -eq 'Enabled' }).Count -eq $features.Count)
)

$json = $result | ConvertTo-Json -Depth 8
if ($OutputPath) {
    $json | Set-Content -Path $OutputPath -Encoding UTF8
}
if ($EmitJson) {
    $json
} else {
    $result
}
