@echo off
setlocal
set "ROOT=%~dp0"
set "EVAL_ROOT=%SAM2_BOWLING_EVAL_ROOT%"
if "%EVAL_ROOT%"=="" set "EVAL_ROOT=C:\Users\student\sam2_bowling_eval"
"%EVAL_ROOT%\.venv\Scripts\python.exe" "%ROOT%quest_bowling_server.py" --host 0.0.0.0 --port 5799
