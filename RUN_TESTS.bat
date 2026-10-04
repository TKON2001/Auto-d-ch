@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "QT_QPA_PLATFORM=offscreen"
call FIND_PYTHON.bat
if not defined FRAME_PYTHON exit /b 1
"%FRAME_PYTHON%" -m unittest discover -s tests -v
exit /b %errorlevel%
