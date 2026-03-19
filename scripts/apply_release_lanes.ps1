param(
    [string]$Repo = "",
    [string]$DevBranch = "dev",
    [string]$ProdBranch = "prod",
    [string[]]$RequiredChecks = @("required-gates"),
    [int]$DevApprovals = 1,
    [int]$ProdApprovals = 1,
    [switch]$SetDefaultDev,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $repoRoot

$baseArgs = @(
    "scripts/setup_github_release_lanes.py",
    "--dev-branch", $DevBranch,
    "--prod-branch", $ProdBranch,
    "--dev-approvals", "$DevApprovals",
    "--prod-approvals", "$ProdApprovals"
)
if ($Repo) { $baseArgs += @("--repo", $Repo) }
foreach ($check in $RequiredChecks) {
    if ($check) { $baseArgs += @("--required-check", $check) }
}
if ($SetDefaultDev) { $baseArgs += "--set-default-dev" }

if ($DryRun) {
    & python @baseArgs --dry-run
    exit $LASTEXITCODE
}

$secureToken = Read-Host "Paste GitHub token (repo administration scope)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

if (-not $token) {
    Write-Error "Token is required."
}

$env:GH_TOKEN = $token
try {
    & python @baseArgs --apply
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & python @baseArgs --check
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:GH_TOKEN -ErrorAction SilentlyContinue
}
