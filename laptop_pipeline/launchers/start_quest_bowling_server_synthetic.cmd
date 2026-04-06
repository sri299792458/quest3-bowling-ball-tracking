@echo off
setlocal
set "ROOT=%~dp0..\"
set "VENV=%ROOT%.venv\Scripts\python.exe"
if not exist "%VENV%" (
  echo Missing laptop_pipeline\.venv. Run laptop_pipeline\setup_laptop_env.ps1 first.
  exit /b 1
)
"%VENV%" "%ROOT%quest_bowling_server.py" --host 0.0.0.0 --port 5799 --analysis-mode synthetic
