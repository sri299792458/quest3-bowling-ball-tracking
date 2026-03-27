$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvPath = Join-Path $repoRoot "laptop_pipeline\.venv"
$requirementsPath = Join-Path $repoRoot "laptop_pipeline\requirements.txt"
$checkpointDir = Join-Path $repoRoot "third_party\sam2\checkpoints"
$checkpointPath = Join-Path $checkpointDir "sam2.1_hiera_tiny.pt"
$checkpointUrl = "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt"

function Resolve-PythonLauncher {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    throw "Python 3 was not found on PATH. Install Python 3.10+ first."
}

$pythonLauncher = Resolve-PythonLauncher
$pythonExe = $pythonLauncher[0]
$pythonArgs = @()
if ($pythonLauncher.Length -gt 1) {
    $pythonArgs = $pythonLauncher[1..($pythonLauncher.Length - 1)]
}
if (-not (Test-Path $venvPath)) {
    & $pythonExe @pythonArgs -m venv $venvPath
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r $requirementsPath

$cudaCheck = @'
import sys
import torch

if not torch.cuda.is_available():
    sys.stderr.write(
        "Torch installed successfully, but CUDA is not available in this venv.\n"
        "Install a CUDA-enabled PyTorch build for this machine, then rerun setup.\n"
    )
    raise SystemExit(1)

print(f"CUDA ready: {torch.cuda.get_device_name(0)}")
'@
& $venvPython -c $cudaCheck

New-Item -ItemType Directory -Force $checkpointDir | Out-Null
if (-not (Test-Path $checkpointPath)) {
    Write-Host "Downloading SAM2 tiny checkpoint..."
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        curl.exe -L $checkpointUrl -o $checkpointPath
    } else {
        Invoke-WebRequest -Uri $checkpointUrl -OutFile $checkpointPath
    }
}

Write-Host ""
Write-Host "Laptop environment ready."
Write-Host "Venv: $venvPath"
Write-Host "Checkpoint: $checkpointPath"
