@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
call FIND_PYTHON.bat
if not defined FRAME_PYTHON goto :missing
"%FRAME_PYTHON%" video_translator.py %*
if errorlevel 1 pause
exit /b
:missing
echo No working Python environment. Run START_WINDOWS.bat to set up.
pause
exit /b 1
