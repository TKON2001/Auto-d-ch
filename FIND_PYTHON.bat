@echo off
rem Called from this application's directory. Validate copied environments.
set "FRAME_PYTHON="
for %%P in (".runtime\Scripts\python.exe" "..\.venv\Scripts\python.exe") do (
  if exist "%%~P" (
    "%%~P" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
      set "FRAME_PYTHON=%%~fP"
      exit /b 0
    )
  )
)
exit /b 1
