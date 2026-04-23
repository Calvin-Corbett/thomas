param(
  [Parameter(Mandatory = $true)]
  [string]$InputPath
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $InputPath)) {
  throw "Input WAV file not found: $InputPath"
}

Add-Type -AssemblyName System.Speech
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::UTF8

$culture = [System.Globalization.CultureInfo]::GetCultureInfo("en-US")
$engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine($culture)

try {
  $grammar = New-Object System.Speech.Recognition.DictationGrammar
  $engine.LoadGrammar($grammar)
  $engine.SetInputToWaveFile($InputPath)
  $result = $engine.Recognize()
  if ($result -and $result.Text) {
    Write-Output $result.Text.Trim()
  }
} finally {
  $engine.Dispose()
}
