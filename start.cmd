@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -B server\app.py %*
  exit /b
)
where py >nul 2>nul && (
  py -3 -B server\app.py %*
  exit /b
)
python -B server\app.py %*
if errorlevel 1 pause
