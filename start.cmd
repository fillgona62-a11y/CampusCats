@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -B server\app.py %*
  exit /b
)
for /d %%D in ("%ProgramFiles%\WindowsApps\OpenAI.CodexPrimaryRuntime.*") do (
  if exist "%%~fD\dependencies\python\python.exe" (
    "%%~fD\dependencies\python\python.exe" -B server\app.py %*
    exit /b
  )
)
py -3 -B server\app.py %*
if errorlevel 1 pause
