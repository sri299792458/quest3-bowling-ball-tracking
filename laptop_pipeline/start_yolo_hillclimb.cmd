@echo off
setlocal

set SCRIPT_DIR=%~dp0
set PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe

if not exist "%PYTHON%" (
  echo Could not find %PYTHON%
  exit /b 1
)

"%PYTHON%" "%SCRIPT_DIR%yolo_hillclimb.py" %*
