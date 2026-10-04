@echo off
setlocal
cd /d "%~dp0"
echo === Frame Video Translator: Windows build ===
py -3 -m venv .build-venv
if errorlevel 1 goto :error
call .build-venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -r requirements.txt
if errorlevel 1 goto :error
python -m pip install pyinstaller
if errorlevel 1 goto :error
python -m PyInstaller --noconfirm --clean --windowed --add-data "component_hashes.json;." --add-data "models;models" --add-data "ffmpeg;ffmpeg" --name FrameVideoTranslator --collect-all easyocr --collect-all cv2 --collect-all torch --collect-all torchvision --collect-all openai --collect-all psutil --collect-all yt_dlp --collect-all openpyxl --collect-all PySide6 --hidden-import=easyocr --hidden-import=cv2 --hidden-import=components video_translator.py
if errorlevel 1 goto :error
if not exist dist\FrameVideoTranslator\ffmpeg mkdir dist\FrameVideoTranslator\ffmpeg
echo.
echo BUILD COMPLETE: %CD%\dist\FrameVideoTranslator\FrameVideoTranslator.exe
echo FFmpeg and OCR models are included in the executable bundle.
echo For distribution, bundle FFmpeg binaries only if you comply with their license terms.
pause
exit /b 0
:error
echo Build failed. Review the error above.
pause
exit /b 1
