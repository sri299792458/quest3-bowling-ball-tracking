$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvPath = Join-Path $repoRoot ".venv"
$requirementsPath = Join-Path $repoRoot "laptop_receiver\requirements-cuda.txt"
$checkpointDir = Join-Path $repoRoot "third_party\sam2\checkpoints"
$checkpointPath = Join-Path $checkpointDir "sam2.1_hiera_tiny.pt"
$checkpointUrls = @(
    "https://huggingface.co/facebook/sam2.1-hiera-tiny/resolve/main/sam2.1_hiera_tiny.pt",
    "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt"
)

function Resolve-PythonLauncher {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    throw "Python 3 was not found on PATH. Install Python 3.10+ first."
}

function Download-File {
    param(
        [string] $Url,
        [string] $OutFile
    )

    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        curl.exe -fL $Url -o $OutFile
        if ($LASTEXITCODE -eq 0) {
            return
        }
        throw "curl.exe failed with exit code $LASTEXITCODE"
    }

    Invoke-WebRequest -Uri $Url -OutFile $OutFile
}

$pythonLauncher = Resolve-PythonLauncher
$pythonExe = $pythonLauncher[0]
$pythonArgs = @()
if ($pythonLauncher.Length -gt 1) {
    $pythonArgs = $pythonLauncher[1..($pythonLauncher.Length - 1)]
}

if (-not (Test-Path $venvPath)) {
    & $pythonExe @pythonArgs -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw "Failed to create repo-local venv." }
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip in repo-local venv." }
& $venvPython -m pip install -r $requirementsPath
if ($LASTEXITCODE -ne 0) { throw "Failed to install laptop receiver requirements." }

$cudaCheck = @'
import sys
import torch

if not torch.cuda.is_available():
    sys.stderr.write(
        "Torch installed successfully, but CUDA is not available in this venv.\n"
        "SAM2 needs a CUDA-capable PyTorch environment on the laptop.\n"
    )
    raise SystemExit(1)

print(f"CUDA ready: {torch.cuda.get_device_name(0)}")
'@
$cudaCheck | & $venvPython -
if ($LASTEXITCODE -ne 0) {
    throw "CUDA verification failed in repo-local venv."
}

New-Item -ItemType Directory -Force $checkpointDir | Out-Null
if (-not (Test-Path $checkpointPath)) {
    $downloaded = $false
    foreach ($checkpointUrl in $checkpointUrls) {
        Write-Host "Downloading SAM2 tiny checkpoint from $checkpointUrl"
        try {
            Download-File -Url $checkpointUrl -OutFile $checkpointPath
            $downloaded = $true
            break
        } catch {
            Write-Warning $_.Exception.Message
            if (Test-Path $checkpointPath) {
                Remove-Item -LiteralPath $checkpointPath -Force
            }
        }
    }

    if (-not $downloaded) {
        throw "Failed to download SAM2 tiny checkpoint."
    }
}

Write-Host ""
Write-Host "Laptop environment ready."
Write-Host "Venv: $venvPath"
Write-Host "SAM2 source: $(Join-Path $repoRoot 'third_party\sam2')"
Write-Host "SAM2 checkpoint: $checkpointPath"
