$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = Split-Path -Parent $scriptDir
$projectRoot = Split-Path -Parent $workspaceRoot

Write-Host "Starting calibrated lane workflow"
Write-Host "Project root: $projectRoot"

python "$scriptDir\run_calibrated_session_workflow.py" @args
