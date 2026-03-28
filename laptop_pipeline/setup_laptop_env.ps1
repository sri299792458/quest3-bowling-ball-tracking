$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvPath = Join-Path $repoRoot "laptop_pipeline\.venv"
$requirementsPath = Join-Path $repoRoot "laptop_pipeline\requirements.txt"
$checkpointDir = Join-Path $repoRoot "third_party\sam2\checkpoints"
$checkpointPath = Join-Path $checkpointDir "sam2.1_hiera_tiny.pt"
$checkpointUrl = "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt"
$torchIndexUrl = "https://download.pytorch.org/whl/cu126"
$torchVersion = "2.7.0"
$torchvisionVersion = "0.22.0"
$tritonWindowsVersion = "3.3.0.post19"

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
    if ($LASTEXITCODE -ne 0) { throw "Failed to create laptop_pipeline venv." }
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip in laptop_pipeline venv." }
& $venvPython -m pip install --upgrade --index-url $torchIndexUrl "torch==$torchVersion" "torchvision==$torchvisionVersion"
if ($LASTEXITCODE -ne 0) { throw "Failed to install CUDA-enabled torch/torchvision in laptop_pipeline venv." }
& $venvPython -m pip install --upgrade "triton-windows==$tritonWindowsVersion"
if ($LASTEXITCODE -ne 0) { throw "Failed to install triton-windows in laptop_pipeline venv." }
& $venvPython -m pip install -r $requirementsPath
if ($LASTEXITCODE -ne 0) { throw "Failed to install laptop_pipeline requirements." }

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
$cudaCheck | & $venvPython -
if ($LASTEXITCODE -ne 0) {
    throw "CUDA verification failed in laptop_pipeline venv."
}

New-Item -ItemType Directory -Force $checkpointDir | Out-Null
if (-not (Test-Path $checkpointPath)) {
    Write-Host "Downloading SAM2 tiny checkpoint..."
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        curl.exe -L $checkpointUrl -o $checkpointPath
    } else {
        Invoke-WebRequest -Uri $checkpointUrl -OutFile $checkpointPath
    }
    if ($LASTEXITCODE -ne 0) { throw "Failed to download SAM2 tiny checkpoint." }
}

& $venvPython (Join-Path $repoRoot "laptop_pipeline\verify_laptop_env.py")
if ($LASTEXITCODE -ne 0) {
    throw "Laptop environment verification failed."
}

Write-Host ""
Write-Host "Laptop environment ready."
Write-Host "Venv: $venvPath"
Write-Host "Checkpoint: $checkpointPath"
