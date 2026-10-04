@echo off
setlocal
cd /d "%~dp0"
call FIND_PYTHON.bat
if defined FRAME_PYTHON (
  call RUN_APP.bat
  exit /b
)
py -3 launcher.py
if errorlevel 1 (
  echo Please install Python x64 with Tkinter and the Python launcher, then run this file again.
  pause
)
