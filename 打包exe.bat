@echo off
rem =========================================================================
rem  Build a single-file exe with PyInstaller.  Chinese help: 使用说明.md
rem  Requires: pip install pillow pyinstaller
rem =========================================================================
setlocal
cd /d "%~dp0"

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [x] pyinstaller not found. Run:  pip install pyinstaller
    pause
    exit /b 1
)

for %%F in ("%~dp0*.pyw") do set "APP=%%~fF"

pyinstaller --noconfirm --onefile --noconsole --name "ImageStripViewer" "%APP%"

echo.
echo Output: dist\ImageStripViewer.exe
echo For Windows 7 target, build with Python 3.8.10 + PyInstaller 4.10.
pause
