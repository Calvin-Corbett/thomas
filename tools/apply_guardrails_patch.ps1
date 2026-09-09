\
    # Best-effort patch applicator (PowerShell).
    # Run from repo root: powershell -ExecutionPolicy Bypass -File tools\apply_guardrails_patch.ps1

    $ErrorActionPreference = "Stop"
    $patches = Get-ChildItem -Path "patches" -Filter "*.patch" | Sort-Object Name
    if ($patches.Count -eq 0) {
      Write-Host "No patches found in patches/"
      exit 2
    }

    try {
      git --version | Out-Null
      $args = @("apply") + ($patches | ForEach-Object { $_.FullName })
      Write-Host "Running: git $($args -join ' ')"
      git @args
      Write-Host "✅ Patches applied."
      exit 0
    } catch {
      Write-Host "⚠️ git apply failed."
      Write-Host $_
      Write-Host ""
      Write-Host "Manual merge path: open INTEGRATION_GUIDE.md and transplant GUARDRAILS blocks."
      exit 1
    }
