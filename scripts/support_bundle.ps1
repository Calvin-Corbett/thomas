[CmdletBinding()]
param(
  [string]$OutputDir = "",
  [int]$MaxLogBytes = 262144,
  [int]$RecentLogCount = 10
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if (-not $OutputDir) {
  $OutputDir = Join-Path $Root "runtime\support"
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$StageDir = Join-Path $OutputDir ("support_bundle_{0}" -f $Stamp)
$ZipPath = Join-Path $OutputDir ("ThomasSupport_{0}.zip" -f $Stamp)

function Redact-Text {
  param([string]$Text)

  $value = if ($null -eq $Text) { "" } else { [string]$Text }
  $userProfilePath = if ($null -eq $env:USERPROFILE) { "" } else { [string]$env:USERPROFILE }
  $local = if ($null -eq $env:LOCALAPPDATA) { "" } else { [string]$env:LOCALAPPDATA }
  $appdata = if ($null -eq $env:APPDATA) { "" } else { [string]$env:APPDATA }

  if ($userProfilePath) { $value = $value.Replace($userProfilePath, "%USERPROFILE%") }
  if ($local) { $value = $value.Replace($local, "%LOCALAPPDATA%") }
  if ($appdata) { $value = $value.Replace($appdata, "%APPDATA%") }

  $value = [regex]::Replace($value, "(?i)(api[_-]?key|access[_-]?token|auth[_-]?token|bearer|password|secret)\s*[:=]\s*[""']?[^""'\r\n]+", '$1=<redacted>')
  $value = [regex]::Replace($value, "(?i)Bearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer <redacted>")
  $value = [regex]::Replace($value, "sk-[A-Za-z0-9_-]{16,}", "sk-<redacted>")
  $value = [regex]::Replace($value, "sk-proj-[A-Za-z0-9_-]{16,}", "sk-proj-<redacted>")
  $value = [regex]::Replace($value, "ghp_[A-Za-z0-9_]{16,}", "ghp_<redacted>")
  $value = [regex]::Replace($value, "github_pat_[A-Za-z0-9_]{16,}", "github_pat_<redacted>")
  return $value
}

function Write-BundleText {
  param(
    [Parameter(Mandatory = $true)][string]$RelativePath,
    [AllowEmptyString()][string[]]$Lines
  )

  $target = Join-Path $StageDir $RelativePath
  $parent = Split-Path -Parent $target
  if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
  $text = ($Lines -join [Environment]::NewLine)
  Set-Content -Path $target -Encoding UTF8 -Value (Redact-Text $text)
}

function Add-CommandOutput {
  param(
    [Parameter(Mandatory = $true)][string]$RelativePath,
    [Parameter(Mandatory = $true)][scriptblock]$Command
  )

  $lines = @()
  try {
    $output = & $Command 2>&1
    if ($output) {
      $lines += ($output | ForEach-Object { [string]$_ })
    } else {
      $lines += "(no output)"
    }
  } catch {
    $lines += ("ERROR: {0}" -f $_.Exception.Message)
  }
  Write-BundleText -RelativePath $RelativePath -Lines $lines
}

function Add-TextFileTail {
  param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$RelativePath
  )

  if (-not (Test-Path $SourcePath -PathType Leaf)) { return }
  try {
    $text = [System.IO.File]::ReadAllText($SourcePath)
    if ($text.Length -gt $MaxLogBytes) {
      $text = "[truncated to last $MaxLogBytes characters]`r`n" + $text.Substring($text.Length - $MaxLogBytes)
    }
    Write-BundleText -RelativePath $RelativePath -Lines @($text)
  } catch {
    Write-BundleText -RelativePath $RelativePath -Lines @("ERROR reading file: $($_.Exception.Message)")
  }
}

try {
  Remove-Item -Recurse -Force $StageDir -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

  Write-BundleText -RelativePath "README.txt" -Lines @(
    "Thomas support bundle",
    "",
    "This ZIP contains redacted diagnostics for troubleshooting install and startup issues.",
    "It should not include API keys, tokens, passwords, environment files, local databases, or full runtime state.",
    "",
    "Send this ZIP with a short description of what failed and any screenshot of the error."
  )

  Write-BundleText -RelativePath "system.txt" -Lines @(
    "created_at=$(Get-Date -Format o)",
    "install_root=$Root",
    "powershell=$($PSVersionTable.PSVersion)",
    "os=$([System.Environment]::OSVersion.VersionString)",
    "is_64_bit_os=$([System.Environment]::Is64BitOperatingSystem)",
    "is_64_bit_process=$([System.Environment]::Is64BitProcess)"
  )

  Add-CommandOutput -RelativePath "os_info.txt" -Command {
    Get-CimInstance Win32_OperatingSystem |
      Select-Object Caption,Version,BuildNumber,OSArchitecture,InstallDate,LastBootUpTime |
      Format-List
  }

  Add-CommandOutput -RelativePath "git_version.txt" -Command {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
      "git unavailable"
      return
    }
    "branch:"
    git branch --show-current
    "commit:"
    git rev-parse --short HEAD
    "describe:"
    git describe --tags --always --dirty
    "status:"
    git status --short --branch
  }

  Add-CommandOutput -RelativePath "python_venv.txt" -Command {
    $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
    "venv_python_exists=$([bool](Test-Path $venvPy -PathType Leaf))"
    if (Test-Path $venvPy -PathType Leaf) {
      & $venvPy --version
      & $venvPy -c "import sys; print(sys.executable); print(sys.version)"
    }
    $py = Get-Command python -ErrorAction SilentlyContinue
    $systemPython = if ($py -and $py.Source) { [string]$py.Source } else { "" }
    "system_python=$systemPython"
    if ($py) { & $py.Source --version }
  }

  Add-CommandOutput -RelativePath "network_port_8899.txt" -Command {
    "Expected local URL: http://127.0.0.1:8899/"
    "Default network scope: loopback-only, same computer."
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
      Get-NetTCPConnection -LocalPort 8899 -ErrorAction SilentlyContinue |
        Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,State,OwningProcess |
        Format-Table -AutoSize
    } else {
      netstat -ano | Select-String ":8899"
    }
  }

  $configPath = Join-Path $Root "thomas.toml"
  Add-TextFileTail -SourcePath $configPath -RelativePath "config_metadata\thomas.toml.redacted.txt"

  $setupDir = Join-Path $Root "runtime\setup"
  if (Test-Path $setupDir) {
    Add-CommandOutput -RelativePath "setup_markers\listing.txt" -Command {
      Get-ChildItem -Path $setupDir -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object Name,Length,LastWriteTime |
        Format-Table -AutoSize
    }
    Get-ChildItem -Path $setupDir -File -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match "^(last_setup|repair_.*)\.txt$" } |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 8 |
      ForEach-Object {
        Add-TextFileTail -SourcePath $_.FullName -RelativePath ("setup_markers\{0}" -f $_.Name)
      }
  } else {
    Write-BundleText -RelativePath "setup_markers\listing.txt" -Lines @("runtime\setup does not exist yet.")
  }

  $logDir = Join-Path $Root "runtime\logs"
  if (Test-Path $logDir) {
    Add-CommandOutput -RelativePath "logs\listing.txt" -Command {
      Get-ChildItem -Path $logDir -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First $RecentLogCount Name,Length,LastWriteTime |
        Format-Table -AutoSize
    }
    $firstRunLog = Join-Path $logDir "first_run_wizard.log"
    Add-TextFileTail -SourcePath $firstRunLog -RelativePath "logs\first_run_wizard.log"
    Get-ChildItem -Path $logDir -File -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First $RecentLogCount |
      ForEach-Object {
        Add-TextFileTail -SourcePath $_.FullName -RelativePath ("logs\recent\{0}" -f $_.Name)
      }
  } else {
    Write-BundleText -RelativePath "logs\listing.txt" -Lines @("runtime\logs does not exist yet.")
  }

  Compress-Archive -Path (Join-Path $StageDir "*") -DestinationPath $ZipPath -Force
  Write-Host ("[thomas] Support bundle written: {0}" -f $ZipPath)
  exit 0
} catch {
  Write-Host ("[thomas] ERROR: support bundle failed: {0}" -f $_.Exception.Message)
  exit 1
} finally {
  Remove-Item -Recurse -Force $StageDir -ErrorAction SilentlyContinue
}
