@echo off
:: ApplyLoop — Windows Installer Launcher
:: Double-click this file to start setup.
:: This .bat wrapper avoids Smart App Control blocking .ps1 files.
::
echo.
echo   ApplyLoop — Windows Setup
echo   =========================
echo.
echo   This will install Python, Node.js, OpenClaw, and configure ApplyLoop.
echo   Press any key to continue or close this window to cancel.
echo.
pause >nul

:: Check for admin rights
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   [!] This script needs Administrator privileges.
    echo   [!] Right-click this file and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

:: Download and run the PowerShell setup script
powershell -ExecutionPolicy Bypass -Command "& { irm 'https://applyloop.vercel.app/setup/setup-windows.ps1' | iex }"

echo.
if %errorlevel% equ 0 (
    echo   Setup complete. If the AI assistant didn't launch, run it manually:
    echo   codex --cd %USERPROFILE%\autoapply
    echo   OR: claude --cd %USERPROFILE%\autoapply
)
echo.
pause
