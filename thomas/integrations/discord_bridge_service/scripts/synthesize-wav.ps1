param(
  [Parameter(Mandatory = $true)]
  [string]$Text,

  [Parameter(Mandatory = $true)]
  [string]$OutputPath,

  [string]$VoiceName = ""
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Speech

$parent = Split-Path -Parent $OutputPath
if ($parent) {
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
}

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

try {
  if ($VoiceName) {
    try {
      $synth.SelectVoice($VoiceName)
    } catch {
      # Fall back to the system default voice when the requested one is unavailable.
    }
  }

  $synth.SetOutputToWaveFile($OutputPath)
  $synth.Speak($Text)
} finally {
  $synth.Dispose()
}

Write-Output $OutputPath
