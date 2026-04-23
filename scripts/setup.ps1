param(
  [switch]$SkipInstall,
  [switch]$SkipDoctor,
  [switch]$WithTestDeps,
  [ValidateSet("auto", "local", "codex", "openai", "anthropic")]
  [string]$Profile = "auto",
  [ValidateSet("auto", "balanced", "hands_on", "hands-on", "review_only", "review-only", "standard", "builder", "locked")]
  [string]$SecurityProfile = "auto",
  [switch]$Easy,
  [switch]$AutoInstallTools,
  [switch]$ConfirmedToolInstall,
  [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Invoke-NativeQuiet {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Args
  )
  $old = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & $Exe @Args 2>$null | Out-Null
    return $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $old
  }
}

function Invoke-Native {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string[]]$Args
  )
  $old = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & $Exe @Args 2>&1 | Out-Host
    return [int]$LASTEXITCODE
  } finally {
    $ErrorActionPreference = $old
  }
}

function Find-SystemPython {
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { return @{ Kind = "python"; Path = $cmd.Source } }
  $cmd = Get-Command py -ErrorAction SilentlyContinue
  if ($cmd) { return @{ Kind = "py"; Path = $cmd.Source } }
  return $null
}

function Get-CommandPathAny {
  param([string[]]$Names)
  foreach ($n in $Names) {
    $cmd = Get-Command $n -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
      return [string]$cmd.Source
    }
  }
  return ""
}

function Test-WingetAvailable {
  $winget = Get-CommandPathAny @("winget", "winget.exe")
  return -not [string]::IsNullOrWhiteSpace($winget)
}

function Install-WithWinget {
  param(
    [Parameter(Mandatory = $true)][string]$PackageId,
    [Parameter(Mandatory = $true)][string]$DisplayName
  )
  if (-not (Test-WingetAvailable)) {
    Write-Host ("[thomas] winget not found. Cannot auto-install {0}." -f $DisplayName)
    return $false
  }

  Write-Host ("[thomas] Installing {0} via winget..." -f $DisplayName)
  $wingetExe = Get-CommandPathAny @("winget", "winget.exe")
  $code = Invoke-Native $wingetExe @(
    "install",
    "--id", $PackageId,
    "--exact",
    "--silent",
    "--accept-package-agreements",
    "--accept-source-agreements",
    "--disable-interactivity"
  )
  if ($code -ne 0) {
    Write-Host ("[thomas] winget install failed for {0} (exit {1})." -f $DisplayName, $code)
    return $false
  }
  return $true
}

function Normalize-SecurityProfileName {
  param(
    [string]$ProfileName,
    [string]$Fallback = "balanced"
  )

  $raw = [string]$ProfileName
  if ([string]::IsNullOrWhiteSpace($raw)) {
    return $Fallback
  }

  $normalized = $raw.Trim().ToLowerInvariant().Replace("-", "_")
  switch ($normalized) {
    "standard" { return "balanced" }
    "default" { return "balanced" }
    "balanced" { return "balanced" }
    "builder" { return "hands_on" }
    "hands_on" { return "hands_on" }
    "locked" { return "review_only" }
    "review_only" { return "review_only" }
    "check_only" { return "review_only" }
    default { return $Fallback }
  }
}

function Get-EffectiveSecurityProfile {
  $candidate = [string]$script:SelectedSecurityProfile
  if ([string]::IsNullOrWhiteSpace($candidate)) {
    return "balanced"
  }
  return (Normalize-SecurityProfileName -ProfileName $candidate -Fallback "balanced")
}

function Test-ToolInstallAllowed {
  $profile = Get-EffectiveSecurityProfile
  return ($profile -ne "review_only")
}

function Confirm-ToolInstall {
  param(
    [Parameter(Mandatory = $true)][string]$DisplayName,
    [Parameter(Mandatory = $true)][string]$Reason,
    [string]$Tradeoff = "Installing tools expands the trusted software on this machine."
  )

  if (-not $AutoInstallTools) {
    return $false
  }
  if (-not (Test-ToolInstallAllowed)) {
    Write-Host ("[thomas] Install Guard mode '{0}' blocks installing {1}." -f (Get-EffectiveSecurityProfile), $DisplayName)
    return $false
  }
  if ($ConfirmedToolInstall) {
    return $true
  }
  if ($NoPrompt) {
    Write-Host ("[thomas] {0} is missing. Setup will not install tools without explicit approval." -f $DisplayName)
    return $false
  }

  Write-Host ""
  Write-Host ("[thomas] Missing tool: {0}" -f $DisplayName)
  Write-Host ("[thomas] Why Thomas wants it: {0}" -f $Reason)
  Write-Host ("[thomas] Security tradeoff: {0}" -f $Tradeoff)
  $approve = (Read-Host "[thomas] Install it now? [y/N]").Trim().ToLowerInvariant()
  return ($approve -eq "y" -or $approve -eq "yes")
}

function Ensure-NodeAndNpmInstalled {
  $node = Get-CommandPathAny @("node", "node.exe")
  $npm = Get-CommandPathAny @("npm", "npm.cmd", "npm.exe")
  if ($node -and $npm) {
    return $true
  }
  if (-not (Confirm-ToolInstall -DisplayName "Node.js LTS" -Reason "Codex CLI depends on Node.js and npm." -Tradeoff "Installing Node.js adds a runtime and package manager that can execute third-party packages.")) {
    return $false
  }
  $ok = Install-WithWinget -PackageId "OpenJS.NodeJS.LTS" -DisplayName "Node.js LTS"
  if (-not $ok) {
    return $false
  }
  $node = Get-CommandPathAny @("node", "node.exe")
  $npm = Get-CommandPathAny @("npm", "npm.cmd", "npm.exe")
  return ($node -and $npm)
}

function Ensure-CodexInstalled {
  if (Test-CodexInstalled) {
    return $true
  }
  if (-not (Confirm-ToolInstall -DisplayName "Codex CLI" -Reason "Codex path uses the official Codex bridge for ChatGPT sign-in and execution." -Tradeoff "Installing the Codex CLI adds a global npm package to this machine.")) {
    return $false
  }
  if (-not (Ensure-NodeAndNpmInstalled)) {
    return $false
  }

  $npm = Get-CommandPathAny @("npm", "npm.cmd", "npm.exe")
  if (-not $npm) {
    Write-Host "[thomas] npm not found after Node install."
    return $false
  }

  Write-Host "[thomas] Installing Codex CLI..."
  $codexInstallArgs = @("install", "-g", "@openai/codex")
  $code = Invoke-Native $npm $codexInstallArgs
  if ($code -ne 0) {
    Write-Host ("[thomas] Codex CLI install failed (exit {0})." -f $code)
    return $false
  }
  return (Test-CodexInstalled)
}

function Ensure-OllamaInstalled {
  $oll = Get-CommandPathAny @("ollama", "ollama.exe")
  if ($oll) {
    return $true
  }
  if (-not (Confirm-ToolInstall -DisplayName "Ollama" -Reason "Local profile requires Ollama to run on-device models." -Tradeoff "Installing Ollama adds a local model runtime and service endpoint.")) {
    return $false
  }
  $ok = Install-WithWinget -PackageId "Ollama.Ollama" -DisplayName "Ollama"
  if (-not $ok) {
    return $false
  }
  $oll = Get-CommandPathAny @("ollama", "ollama.exe")
  return -not [string]::IsNullOrWhiteSpace($oll)
}

function Ensure-SystemPython {
  $found = Find-SystemPython
  if ($found) {
    return $found
  }
  if (-not (Confirm-ToolInstall -DisplayName "Python 3.11+" -Reason "Thomas itself needs Python to create the virtual environment and run." -Tradeoff "Installing Python adds a general-purpose interpreter and package tooling.")) {
    return $null
  }

  Write-Host "[thomas] Python not found. Installing Python..."
  $installed = $false
  $installed = Install-WithWinget -PackageId "Python.Python.3.11" -DisplayName "Python 3.11"
  if (-not $installed) {
    $installed = Install-WithWinget -PackageId "Python.Python.3.12" -DisplayName "Python 3.12"
  }
  if (-not $installed) {
    return $null
  }

  return Find-SystemPython
}

function Read-TomlText {
  param([string]$Path)
  if (-not (Test-Path $Path)) {
    throw "[thomas] Missing config file: $Path"
  }
  return Get-Content -Path $Path -Raw
}

function Get-ConfiguredProfileNames {
  param([string]$TomlText)
  $matches = [regex]::Matches($TomlText, '(?m)^\[models\.(?<name>[^\]]+)\]\s*$')
  $names = New-Object System.Collections.Generic.List[string]
  foreach ($m in $matches) {
    if (-not $m.Success) { continue }
    $n = [string]$m.Groups["name"].Value
    if ([string]::IsNullOrWhiteSpace($n)) { continue }
    $n = $n.Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($n)) { continue }
    if (-not $names.Contains($n)) {
      $names.Add($n)
    }
  }
  return @($names)
}

function Get-DefaultModelName {
  param([string]$TomlText)
  $m = [regex]::Match($TomlText, '(?m)^\s*default_model\s*=\s*"(?<value>[^"]+)"')
  if ($m.Success) {
    return $m.Groups["value"].Value.Trim().ToLowerInvariant()
  }
  return ""
}

function Set-DefaultModelName {
  param(
    [string]$Path,
    [string]$ModelName
  )
  $content = Read-TomlText $Path
  $replacement = "default_model = `"$ModelName`""
  if ($content -match '(?m)^\s*default_model\s*=\s*"[^"]*"\s*$') {
    $updated = $content -replace '(?m)^\s*default_model\s*=\s*"[^"]*"\s*$', $replacement
  } else {
    $updated = $replacement + "`r`n" + $content
  }
  if ($updated -ne $content) {
    $resolved = (Resolve-Path $Path).Path
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($resolved, $updated, $utf8NoBom)
    Write-Host "[thomas] default_model set to '$ModelName'."
  }
}

function Get-ConfiguredSecurityProfileName {
  param([string]$TomlText)
  $section = [regex]::Match($TomlText, '(?ms)^\[security\]\s*(?<body>.*?)(?=^\[|\z)')
  if (-not $section.Success) {
    return "balanced"
  }
  $m = [regex]::Match($section.Groups["body"].Value, '(?m)^\s*profile\s*=\s*"(?<value>[^"]+)"')
  if ($m.Success) {
    return (Normalize-SecurityProfileName -ProfileName $m.Groups["value"].Value -Fallback "balanced")
  }
  return "balanced"
}

function Set-SecurityProfileName {
  param(
    [string]$Path,
    [string]$ProfileName
  )
  $content = Read-TomlText $Path
  $profileLine = "profile = `"$ProfileName`""
  $updated = $content
  if ($content -match '(?ms)^\[security\]\s*(?<body>.*?)(?=^\[|\z)') {
    $sectionBody = $Matches["body"]
    if ($sectionBody -match '(?m)^\s*profile\s*=\s*"[^"]*"\s*$') {
      $replacementBody = $sectionBody -replace '(?m)^\s*profile\s*=\s*"[^"]*"\s*$', $profileLine
      $updated = $content -replace '(?ms)(^\[security\]\s*)(.*?)(?=^\[|\z)', ('$1' + $replacementBody)
    } else {
      $updated = $content -replace '(?ms)(^\[security\]\s*)(.*?)(?=^\[|\z)', ('$1' + $sectionBody.TrimEnd() + "`r`n" + $profileLine + "`r`n")
    }
  } else {
    $updated = $content.TrimEnd() + "`r`n`r`n[security]`r`n" + $profileLine + "`r`n"
  }
  if ($updated -ne $content) {
    $resolved = (Resolve-Path $Path).Path
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($resolved, $updated, $utf8NoBom)
    Write-Host "[thomas] security.profile set to '$ProfileName'."
  }
}

function Prompt-SecurityProfileChoice {
  param([string]$CurrentProfile)
  Write-Host ""
  Write-Host "[thomas] Choose an Install Guard mode:"
  Write-Host "  1) balanced     (recommended: no silent installs, explicit confirmation required)"
  Write-Host "  2) hands_on     (same protection, tuned for active product work with the assistant)"
  Write-Host "  3) review_only  (check-only mode; Thomas explains changes but never installs tools)"
  Write-Host ("  4) keep current ({0})" -f $CurrentProfile)

  while ($true) {
    $choice = (Read-Host "Enter 1-4 [4]").Trim()
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "4" }
    switch ($choice) {
      "1" { return "balanced" }
      "2" { return "hands_on" }
      "3" { return "review_only" }
      "4" { return $CurrentProfile }
      default { Write-Host "[thomas] Invalid choice. Enter 1, 2, 3, or 4." }
    }
  }
}

function Resolve-SelectedSecurityProfile {
  param(
    [string]$ConfiguredProfile,
    [string]$RequestedProfile
  )

  $configured = [string]$ConfiguredProfile
  if ([string]::IsNullOrWhiteSpace($configured)) {
    $configured = "balanced"
  }
  $configured = Normalize-SecurityProfileName -ProfileName $configured -Fallback "balanced"

  $requested = [string]$RequestedProfile
  if ([string]::IsNullOrWhiteSpace($requested)) {
    $requested = "auto"
  }
  $requested = $requested.Trim().ToLowerInvariant().Replace("-", "_")

  if ($requested -ne "auto") {
    $requested = Normalize-SecurityProfileName -ProfileName $requested -Fallback $configured
  }

  if ($configured -eq "review_only" -and $requested -ne "auto" -and $requested -ne "review_only") {
    Write-Host "[thomas] Configured Install Guard mode is review_only. Ignoring weaker override."
    return "review_only"
  }

  if ($requested -eq "auto") {
    if ($NoPrompt) {
      return $configured
    }
    return (Prompt-SecurityProfileChoice -CurrentProfile $configured)
  }

  return $requested
}

function Get-ProfileApiKeyFromToml {
  param(
    [string]$TomlText,
    [string]$ModelName
  )
  $escaped = [regex]::Escape($ModelName)
  $pattern = "(?ms)^\[models\.$escaped\]\s*(?<body>.*?)(?=^\[|\z)"
  $section = [regex]::Match($TomlText, $pattern)
  if (-not $section.Success) { return "" }

  $api = [regex]::Match($section.Groups["body"].Value, '(?m)^\s*api_key\s*=\s*"(?<key>[^"]*)"')
  if (-not $api.Success) { return "" }
  return $api.Groups["key"].Value.Trim()
}

function Get-CloudEnvVarName {
  param([string]$ModelName)
  return "THOMAS_MODELS_" + $ModelName.ToUpperInvariant() + "_API_KEY"
}

function Test-CloudKeyConfigured {
  param(
    [string]$TomlText,
    [string]$ModelName
  )
  $envName = Get-CloudEnvVarName $ModelName
  $envValue = [Environment]::GetEnvironmentVariable($envName, "Process")
  if (-not $envValue) { $envValue = [Environment]::GetEnvironmentVariable($envName, "User") }
  if (-not $envValue) { $envValue = [Environment]::GetEnvironmentVariable($envName, "Machine") }
  if ($envValue) { return $true }

  $cfgValue = Get-ProfileApiKeyFromToml -TomlText $TomlText -ModelName $ModelName
  return -not [string]::IsNullOrWhiteSpace($cfgValue)
}

function Ensure-OllamaRunning {
  $oll = Get-Command ollama -ErrorAction SilentlyContinue
  if (-not $oll) {
    Write-Host "[thomas] Ollama not found. Install from https://ollama.com if using local profile."
    return $false
  }

  $listening = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
  if ($listening) {
    return $true
  }

  Write-Host "[thomas] Starting Ollama on :11434..."
  try {
    Start-Process -FilePath $oll.Source -ArgumentList @("serve") -WindowStyle Minimized | Out-Null
    Start-Sleep -Milliseconds 800
  } catch {
    Write-Host "[thomas] Could not auto-start Ollama. Run: ollama serve"
    return $false
  }
  return $true
}

function Test-CodexInstalled {
  $cmd = Get-Command codex -ErrorAction SilentlyContinue
  if ($cmd) { return $true }
  $cmd = Get-Command codex.cmd -ErrorAction SilentlyContinue
  if ($cmd) { return $true }
  $cmd = Get-Command codex.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $true }
  return $false
}

function Test-CodexLoggedIn {
  param([string]$PythonExe)
  $old = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $out = & $PythonExe -m thomas codex status 2>&1
    $text = ($out | Out-String)
    return ($text -match "Signed in as")
  } finally {
    $ErrorActionPreference = $old
  }
}

function Test-ProfileReady {
  param(
    [string]$ModelName,
    [string]$TomlText,
    [string]$PythonExe
  )

  switch ($ModelName) {
    "local" {
      $oll = Get-Command ollama -ErrorAction SilentlyContinue
      if (-not $oll) {
        return [pscustomobject]@{ Ready = $false; Message = "Local profile requires Ollama."; Action = "Install Ollama: https://ollama.com" }
      }
      return [pscustomobject]@{ Ready = $true; Message = "Local profile detected."; Action = "" }
    }
    "codex" {
      if (-not (Test-CodexInstalled)) {
        return [pscustomobject]@{ Ready = $false; Message = "Codex CLI is not installed."; Action = "Install Node.js, then install @openai/codex with explicit approval." }
      }
      if (-not (Test-CodexLoggedIn -PythonExe $PythonExe)) {
        return [pscustomobject]@{ Ready = $false; Message = "Codex CLI is installed but not logged in."; Action = "Run: .\\.venv\\Scripts\\python.exe -m thomas codex login" }
      }
      return [pscustomobject]@{ Ready = $true; Message = "Codex profile is ready."; Action = "" }
    }
    "openai" {
      if (-not (Test-CloudKeyConfigured -TomlText $TomlText -ModelName "openai")) {
        return [pscustomobject]@{ Ready = $false; Message = "OpenAI profile has no API key configured."; Action = "Set THOMAS_MODELS_OPENAI_API_KEY or add models.openai.api_key." }
      }
      return [pscustomobject]@{ Ready = $true; Message = "OpenAI profile key detected."; Action = "" }
    }
    "anthropic" {
      if (-not (Test-CloudKeyConfigured -TomlText $TomlText -ModelName "anthropic")) {
        return [pscustomobject]@{ Ready = $false; Message = "Anthropic profile has no API key configured."; Action = "Set THOMAS_MODELS_ANTHROPIC_API_KEY or add models.anthropic.api_key." }
      }
      return [pscustomobject]@{ Ready = $true; Message = "Anthropic profile key detected."; Action = "" }
    }
    default {
      if (-not (Test-CloudKeyConfigured -TomlText $TomlText -ModelName $ModelName)) {
        return [pscustomobject]@{
          Ready = $false
          Message = "Profile '$ModelName' has no API key configured."
          Action = ("Set " + (Get-CloudEnvVarName $ModelName) + " or add models." + $ModelName + ".api_key.")
        }
      }
      return [pscustomobject]@{ Ready = $true; Message = "Profile '$ModelName' key detected."; Action = "" }
    }
  }
}

function Resolve-EasyProfile {
  param(
    [string]$TomlText,
    [string]$CurrentModel,
    [string]$PythonExe
  )

  $configured = Get-ConfiguredProfileNames -TomlText $TomlText
  $priority = @()
  if (-not [string]::IsNullOrWhiteSpace($CurrentModel)) {
    $priority += $CurrentModel
  }
  $priority += @("codex", "local", "openrouter", "groq", "openai", "anthropic")
  $priority += $configured

  $seen = @{}
  foreach ($raw in $priority) {
    $candidate = [string]$raw
    if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
    $candidate = $candidate.Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
    if ($seen.ContainsKey($candidate)) { continue }
    $seen[$candidate] = $true
    $status = Test-ProfileReady -ModelName $candidate -TomlText $TomlText -PythonExe $PythonExe
    if ($status.Ready) {
      return [pscustomobject]@{
        Profile = $candidate
        Ready = $true
        Reason = [string]$status.Message
      }
    }
  }

  $fallback = ""
  if ($configured.Count -gt 0) {
    $fallback = [string]$configured[0]
  } elseif (-not [string]::IsNullOrWhiteSpace($CurrentModel)) {
    $fallback = [string]$CurrentModel
  } else {
    $fallback = "local"
  }
  $fallback = $fallback.Trim().ToLowerInvariant()
  return [pscustomobject]@{
    Profile = $fallback
    Ready = $false
    Reason = "No fully ready profile detected yet."
  }
}

function Prompt-ProfileChoice {
  param([string]$CurrentModel)

  Write-Host ""
  Write-Host "[thomas] Choose your default model profile:"
  Write-Host "  1) local      (Ollama on this PC)"
  Write-Host "  2) codex      (ChatGPT account via codex CLI)"
  Write-Host "  3) openai     (OpenAI API key)"
  Write-Host "  4) anthropic  (Anthropic API key)"
  Write-Host "  5) keep current ($CurrentModel)"

  while ($true) {
    $choice = (Read-Host "Enter 1-5 [5]").Trim()
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "5" }
    switch ($choice) {
      "1" { return "local" }
      "2" { return "codex" }
      "3" { return "openai" }
      "4" { return "anthropic" }
      "5" { return $CurrentModel }
      default { Write-Host "[thomas] Invalid choice. Enter 1, 2, 3, 4, or 5." }
    }
  }
}

function MaybeCaptureCloudKey {
  param([string]$ModelName)
  if ($NoPrompt) { return }
  if ($ModelName -notin @("openai", "anthropic")) { return }

  $envName = Get-CloudEnvVarName $ModelName
  $existing = [Environment]::GetEnvironmentVariable($envName, "User")
  if ($existing) {
    Write-Host "[thomas] Found user-level $envName."
    return
  }

  $key = Read-Host "Paste $ModelName API key now (or press Enter to skip)"
  if ([string]::IsNullOrWhiteSpace($key)) {
    Write-Host "[thomas] Skipped key input."
    return
  }

  [Environment]::SetEnvironmentVariable($envName, $key, "User")
  [Environment]::SetEnvironmentVariable($envName, $key, "Process")
  Write-Host "[thomas] Saved $envName to User environment."
}

Write-Host "[thomas] Setup starting..."
Write-Host "[thomas] Root: $Root"

$ConfigPath = Join-Path $Root "thomas.toml"
$TomlText = Read-TomlText $ConfigPath
$CurrentSecurityProfile = Get-ConfiguredSecurityProfileName -TomlText $TomlText
if ([string]::IsNullOrWhiteSpace($CurrentSecurityProfile)) {
  $CurrentSecurityProfile = "balanced"
}
$script:SelectedSecurityProfile = Resolve-SelectedSecurityProfile -ConfiguredProfile $CurrentSecurityProfile -RequestedProfile $SecurityProfile
Write-Host ("[thomas] Install Guard mode '{0}' active." -f $script:SelectedSecurityProfile)

$SysPy = Ensure-SystemPython
if (-not $SysPy) {
  Write-Host "[thomas] ERROR: Python not found in PATH."
  Write-Host "[thomas] Install Python 3.10+ and re-run setup.cmd."
  exit 2
}

$VenvPy = Join-Path $Root ".venv\\Scripts\\python.exe"
if (-not (Test-Path $VenvPy)) {
  Write-Host "[thomas] Creating virtual environment..."
  if ($SysPy.Kind -eq "py") {
    & $SysPy.Path -3 -m venv .venv
  } else {
    & $SysPy.Path -m venv .venv
  }
  if (-not (Test-Path $VenvPy)) {
    Write-Host "[thomas] ERROR: virtual environment creation failed."
    exit 2
  }
}

if (-not $SkipInstall) {
  Write-Host "[thomas] Installing dependencies..."
  $code = Invoke-Native $VenvPy @("-m", "pip", "install", "--upgrade", "pip")
  if ($code -ne 0) { throw "[thomas] pip upgrade failed (exit $code)" }

  $installTarget = ".[server,repl]"
  if ($WithTestDeps) {
    $installTarget = ".[server,repl]"
  }
  $code = Invoke-Native $VenvPy @("-m", "pip", "install", "-e", $installTarget)
  if ($code -ne 0) { throw "[thomas] pip install failed (exit $code)" }

  if ($WithTestDeps) {
    $code = Invoke-Native $VenvPy @("-m", "pip", "install", "pytest")
    if ($code -ne 0) { throw "[thomas] pytest install failed (exit $code)" }
  }
}

$probe = Invoke-NativeQuiet $VenvPy @("-c", "import click, httpx, aiohttp")
if ($probe -ne 0) {
  Write-Host "[thomas] ERROR: dependency probe failed."
  Write-Host '[thomas] Run: .\.venv\Scripts\python.exe -m pip install -e ".[server,repl]"'
  exit 2
}

$CurrentDefaultModel = Get-DefaultModelName $TomlText
if (-not $CurrentDefaultModel) {
  $CurrentDefaultModel = "local"
}

$SelectedProfile = $Profile
if ($Profile -eq "auto") {
  if ($Easy) {
    $easySelection = Resolve-EasyProfile -TomlText $TomlText -CurrentModel $CurrentDefaultModel -PythonExe $VenvPy
    $SelectedProfile = [string]$easySelection.Profile
    Write-Host ("[thomas] Easy setup selected profile '{0}'." -f $SelectedProfile)
    if ($easySelection.Reason) {
      Write-Host ("[thomas] " + [string]$easySelection.Reason)
    }
    if (-not $easySelection.Ready) {
      Write-Host "[thomas] Easy setup will not install prerequisites silently. Missing tools will be surfaced for approval later."
    }
  } else {
    $currentStatus = Test-ProfileReady -ModelName $CurrentDefaultModel -TomlText $TomlText -PythonExe $VenvPy

    if ($NoPrompt) {
      $SelectedProfile = $CurrentDefaultModel
    } elseif ($currentStatus.Ready) {
      $keep = (Read-Host "[thomas] Keep current default model '$CurrentDefaultModel'? [Y/n]").Trim().ToLowerInvariant()
      if ([string]::IsNullOrWhiteSpace($keep) -or $keep -eq "y" -or $keep -eq "yes") {
        $SelectedProfile = $CurrentDefaultModel
      } else {
        $SelectedProfile = Prompt-ProfileChoice -CurrentModel $CurrentDefaultModel
      }
    } else {
      Write-Host "[thomas] Current default model '$CurrentDefaultModel' is not ready."
      Write-Host ("[thomas] Reason: " + $currentStatus.Message)
      if ($currentStatus.Action) {
        Write-Host ("[thomas] Fix: " + $currentStatus.Action)
      }
      $SelectedProfile = Prompt-ProfileChoice -CurrentModel $CurrentDefaultModel
    }
  }
}

Set-DefaultModelName -Path $ConfigPath -ModelName $SelectedProfile
Set-SecurityProfileName -Path $ConfigPath -ProfileName $script:SelectedSecurityProfile

if ($SelectedProfile -eq "local") {
  if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Ensure-OllamaInstalled | Out-Null
  }
  Ensure-OllamaRunning | Out-Null
}
if ($SelectedProfile -eq "codex") {
  if (-not (Test-CodexInstalled)) {
    Ensure-CodexInstalled | Out-Null
  }
  if (-not (Test-CodexInstalled)) {
    Write-Host "[thomas] Codex CLI not found. Install Node.js and @openai/codex only after explicit approval."
  } elseif (-not (Test-CodexLoggedIn -PythonExe $VenvPy)) {
    if (-not $NoPrompt) {
      $loginNow = (Read-Host "[thomas] Run Codex login now? [Y/n]").Trim().ToLowerInvariant()
      if ([string]::IsNullOrWhiteSpace($loginNow) -or $loginNow -eq "y" -or $loginNow -eq "yes") {
        & $VenvPy -m thomas codex login
      }
    }
  }
}

MaybeCaptureCloudKey -ModelName $SelectedProfile

$TomlText = Read-TomlText $ConfigPath
$selectedStatus = Test-ProfileReady -ModelName $SelectedProfile -TomlText $TomlText -PythonExe $VenvPy
if (-not $selectedStatus.Ready) {
  Write-Host ""
  Write-Host "[thomas] WARNING: selected profile is not fully ready."
  Write-Host ("[thomas] " + $selectedStatus.Message)
  if ($selectedStatus.Action) {
    Write-Host ("[thomas] " + $selectedStatus.Action)
  }
  Write-Host "[thomas] You can still continue. The in-app onboarding wizard will help finish setup."
}

$setupDir = Join-Path $Root "runtime\\setup"
New-Item -ItemType Directory -Force -Path $setupDir | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$statusPath = Join-Path $setupDir "last_setup.txt"
Set-Content -Path $statusPath -Encoding UTF8 -Value @(
  "timestamp=$stamp"
  "profile=$SelectedProfile"
  "security_profile=$($script:SelectedSecurityProfile)"
  "ready=$($selectedStatus.Ready)"
  "easy_mode=$($Easy.IsPresent)"
  "auto_install_tools=$($AutoInstallTools.IsPresent)"
  "confirmed_tool_install=$($ConfirmedToolInstall.IsPresent)"
)

if (-not $SkipDoctor) {
  Write-Host "[thomas] Running doctor..."
  $code = Invoke-Native $VenvPy @("-m", "thomas", "doctor")
  if ($code -ne 0) {
    Write-Host "[thomas] WARNING: doctor reported issues."
    Write-Host "[thomas] Continue after fixing doctor output."
  }
}

Write-Host ""
Write-Host "[thomas] Setup complete."
Write-Host "[thomas] Selected profile: $SelectedProfile"
Write-Host ("[thomas] Install Guard mode: {0}" -f $script:SelectedSecurityProfile)
Write-Host "[thomas] Status file: $statusPath"
Write-Host "[thomas] Next:"
Write-Host "  1) Run run-ui.cmd"
Write-Host "  2) Open http://127.0.0.1:8899 and complete the Onboarding Wizard"
Write-Host "  3) If needed: .\\.venv\\Scripts\\python.exe -m thomas doctor --full"
Write-Host ""
