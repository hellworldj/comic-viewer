@echo off
rem ==========================================================================
rem  Lantern Image Viewer - launcher (ASCII only, safe for cmd codepage)
rem  Finds a Python that can "import tkinter,PIL", then starts the viewer.
rem  Chinese help: see 使用说明.md
rem ==========================================================================
setlocal
cd /d "%~dp0"

set "PYEXE="

call :probe "%~dp0python\pythonw.exe"
if defined PYEXE goto run
call :probe "D:\tool\Python38\pythonw.exe"
if defined PYEXE goto run
call :probe "C:\Python38\pythonw.exe"
if defined PYEXE goto run
call :probe "C:\Python39\pythonw.exe"
if defined PYEXE goto run
call :probe "C:\Python310\pythonw.exe"
if defined PYEXE goto run
call :probe "C:\Python311\pythonw.exe"
if defined PYEXE goto run
call :probe "C:\Python312\pythonw.exe"
if defined PYEXE goto run
call :probe "C:\Python313\pythonw.exe"
if defined PYEXE goto run

for /f "delims=" %%I in ('where pythonw 2^>nul') do (
    call :probe "%%I"
    if defined PYEXE goto run
)

echo.
echo   [x] No usable Python found. tkinter + Pillow are required.
echo.
echo   1. Install Python 3.8 or newer: https://www.python.org/downloads/
echo      (keep "Add Python to PATH" and tcl/tk checked)
echo   2. Install image library:   pip install pillow
echo   3. Or drop a portable Python into .\python\ (python\pythonw.exe)
echo.
echo   See 使用说明.md for details.
echo.
pause
exit /b 1

:probe
if defined PYEXE exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import tkinter,PIL" >nul 2>&1
if errorlevel 1 exit /b 0
set "PYEXE=%~1"
exit /b 0

:run
if /i "%~1"=="probe" (
    echo Python: %PYEXE%
    exit /b 0
)
for %%F in ("%~dp0*.pyw") do set "APP=%%~fF"
start "" "%PYEXE%" "%APP%"
exit /b 0
