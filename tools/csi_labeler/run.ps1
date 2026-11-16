# Launch the CSI labeled data collector.
# Uses (in order): $env:CSI_LABELER_PYTHON, local .venv, or creates a local .venv.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$local = Join-Path $here ".venv\Scripts\python.exe"

$py = $null
if ($env:CSI_LABELER_PYTHON -and (Test-Path $env:CSI_LABELER_PYTHON)) {
    $py = $env:CSI_LABELER_PYTHON
} elseif (Test-Path $local) {
    $py = $local
} else {
    Write-Host "Creating local virtualenv (.venv)..."
    python -m venv (Join-Path $here ".venv")
    $py = $local
    & $py -m pip install --upgrade pip
    & $py -m pip install -r (Join-Path $here "requirements.txt")
}

& $py (Join-Path $here "csi_labeler.py") @args
