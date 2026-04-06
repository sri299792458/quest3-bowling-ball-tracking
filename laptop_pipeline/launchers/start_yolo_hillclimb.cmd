@echo off
setlocal

set SCRIPT_DIR=%~dp0
set PIPELINE_ROOT=%SCRIPT_DIR%..\
set PYTHON=%PIPELINE_ROOT%.venv\Scripts\python.exe

if not exist "%PYTHON%" (
  echo Could not find %PYTHON%
  exit /b 1
)

"%PYTHON%" "%PIPELINE_ROOT%training\yolo_hillclimb.py" %*
