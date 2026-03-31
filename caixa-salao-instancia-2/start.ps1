$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCandidates = @(
  (Join-Path $projectDir ".venv\\Scripts\\python.exe"),
  (Join-Path (Split-Path $projectDir -Parent) ".venv\\Scripts\\python.exe"),
  "python"
)

$pythonExe = $null
foreach ($candidate in $pythonCandidates) {
  if ($candidate -eq "python") {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
      $pythonExe = $command.Source
      break
    }
  } elseif (Test-Path $candidate) {
    $pythonExe = $candidate
    break
  }
}

if (-not $pythonExe) {
  Write-Error "Python nao encontrado. Ative um ambiente virtual ou instale o Python."
  exit 1
}

$env:PORT = "8081"
Set-Location $projectDir
& $pythonExe "app.py"
