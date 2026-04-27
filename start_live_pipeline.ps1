param(
    [switch]$LaneOnly,
    [switch]$NoSam2
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$logRoot = Join-Path $repoRoot "Temp\live_pipeline_logs"
$yoloCheckpoint = Join-Path $repoRoot "models\bowling_ball_yolo26s_img1280_lightaug_v3\weights\best.pt"
$sam2Root = Join-Path $repoRoot "third_party\sam2"
$sam2Checkpoint = Join-Path $repoRoot "third_party\sam2\checkpoints\sam2.1_hiera_tiny.pt"

function Stop-ExistingLiveProcess {
    $moduleNames = @(
        "laptop_receiver.live_stream_receiver",
        "laptop_receiver.run_live_session_pipeline"
    )

    Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
        Where-Object {
            $commandLine = $_.CommandLine
            if ([string]::IsNullOrWhiteSpace($commandLine)) {
                return $false
            }
            foreach ($moduleName in $moduleNames) {
                if ($commandLine.Contains($moduleName)) {
                    return $true
                }
            }
            return $false
        } |
        ForEach-Object {
            Write-Host "Stopping stale live process $($_.ProcessId): $($_.CommandLine)"
            Stop-Process -Id $_.ProcessId -Force
        }
}

function Wait-ReceiverHealth {
    param(
        [System.Diagnostics.Process]$Process,
        [int]$TimeoutSeconds = 15
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if ($Process.HasExited) {
            throw "live_stream_receiver exited before becoming healthy. Check $receiverStdout and $receiverStderr"
        }

        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8768/health" -UseBasicParsing -TimeoutSec 1
            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    } while ((Get-Date) -lt $deadline)

    throw "Timed out waiting for live_stream_receiver health on http://127.0.0.1:8768/health"
}

if (-not (Test-Path $python)) {
    throw "Missing repo venv python: $python. Run .\laptop_receiver\setup_laptop_env.ps1 first."
}

if (-not $LaneOnly -and -not (Test-Path $yoloCheckpoint)) {
    throw "Missing YOLO26s checkpoint: $yoloCheckpoint"
}

if (-not $LaneOnly -and -not $NoSam2) {
    if (-not (Test-Path $sam2Root)) {
        throw "Missing SAM2 repo: $sam2Root. Run .\laptop_receiver\setup_laptop_env.ps1 first."
    }
    if (-not (Test-Path $sam2Checkpoint)) {
        throw "Missing SAM2 checkpoint: $sam2Checkpoint. Run .\laptop_receiver\setup_laptop_env.ps1 first."
    }
}

Set-Location $repoRoot
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$receiverStdout = Join-Path $logRoot "receiver_$stamp.out.log"
$receiverStderr = Join-Path $logRoot "receiver_$stamp.err.log"

Stop-ExistingLiveProcess

Write-Host "Starting live_stream_receiver..."
$receiver = Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "laptop_receiver.live_stream_receiver") `
    -WorkingDirectory $repoRoot `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput $receiverStdout `
    -RedirectStandardError $receiverStderr

try {
    Wait-ReceiverHealth -Process $receiver

    Write-Host "Receiver is healthy."
    Write-Host "Receiver logs:"
    Write-Host "  stdout: $receiverStdout"
    Write-Host "  stderr: $receiverStderr"

    $pipelineArgs = @("-m", "laptop_receiver.run_live_session_pipeline")
    if (-not $LaneOnly) {
        $pipelineArgs += @("--yolo-checkpoint", $yoloCheckpoint)
        if (-not $NoSam2) {
            $pipelineArgs += "--run-sam2"
        }
    }

    Write-Host "Starting live session pipeline in this terminal."
    Write-Host "Press Ctrl+C to stop the pipeline and receiver."
    & $python @pipelineArgs
    $pipelineExitCode = $LASTEXITCODE
}
finally {
    if ($receiver -and -not $receiver.HasExited) {
        Write-Host "Stopping live_stream_receiver PID $($receiver.Id)..."
        Stop-Process -Id $receiver.Id -Force
    }
}

exit $pipelineExitCode
