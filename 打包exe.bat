@echo off
rem Build single-file exe. Requires: pip install pillow pyinstaller
setlocal
cd /d "%~dp0"
where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [x] pyinstaller not found. Run: pip install pyinstaller
    pause
    exit /b 1
)
pyinstaller --noconfirm --clean --onefile --noconsole --name "看图工具" 看图工具.pyw
echo.
echo Output: dist\看图工具.exe   (本机已生成可直接用)
echo Win7 目标需用 Python 3.8.10 + PyInstaller 4.10 打包。
pause
