@echo off
:: ApplyLoop — One-click launcher for Windows
:: Double-click to start. Runs Claude Code with full permissions.
:: Requests admin access automatically.

:: Check for admin rights — auto-elevate if not admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator access...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo   ╔══════════════════════════════════════════╗
echo   ║     ApplyLoop — Starting...              ║
echo   ╚══════════════════════════════════════════╝
echo.

set INSTALL_DIR=%USERPROFILE%\ApplyLoop

:: Check if setup is done
if not exist "%INSTALL_DIR%\AGENTS.md" (
    echo   Setup not complete. Run the setup script first:
    echo   applyloop.vercel.app/setup-complete
    echo.
    pause
    exit /b 1
)

:: Pull latest updates from repo
echo   Checking for updates...
if exist "%INSTALL_DIR%\repo\.git" (
    cd /d "%INSTALL_DIR%\repo"
    git pull origin main >nul 2>&1
    robocopy "%INSTALL_DIR%\repo" "%INSTALL_DIR%" /E /XD .git /NFL /NDL /NJH /NJS >nul 2>&1
    echo   Updates applied.
) else if exist "%INSTALL_DIR%\.git" (
    cd /d "%INSTALL_DIR%"
    git pull origin main >nul 2>&1
    echo   Updates applied.
) else (
    echo   No git repo found — skipping update check.
)

echo.
echo   Starting ApplyLoop with Claude Code...
echo   (This window will stay open while ApplyLoop runs)
echo.

cd /d "%INSTALL_DIR%"
claude.cmd --dangerously-skip-permissions --cd "%INSTALL_DIR%" "Read AGENTS.md. You are ApplyLoop. Start the jiggler, then begin the scout→filter→apply loop using openclaw browser commands. Do NOT use web search. Do NOT run worker.py."

echo.
echo   ApplyLoop stopped.
pause
