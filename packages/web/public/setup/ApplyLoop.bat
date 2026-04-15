@echo off
:: ApplyLoop — Windows launcher (parity with macOS .app/Contents/MacOS/launcher)
:: Runs packages/desktop/launch.py in the bundled venv, which starts FastAPI +
:: pywebview + the PTY backend (pywinpty) which spawns claude. Mirrors Mac path
:: exactly so the UI/API/PTY behavior is identical across platforms.

setlocal EnableDelayedExpansion

set "INSTALL_DIR=%USERPROFILE%\ApplyLoop"
set "LOG_DIR=%USERPROFILE%\.applyloop"
set "LOG_FILE=%LOG_DIR%\desktop.log"
set "VENV_PY=%INSTALL_DIR%\venv\Scripts\python.exe"
set "LAUNCH_PY=%INSTALL_DIR%\packages\desktop\launch.py"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
if not exist "%LOG_DIR%\workspace" mkdir "%LOG_DIR%\workspace" >nul 2>&1

:: Bail early with an actionable message if setup never completed.
if not exist "%INSTALL_DIR%\AGENTS.md" (
    echo.
    echo   ApplyLoop is not installed yet.
    echo   Run the setup script first:
    echo     https://applyloop.vercel.app/setup
    echo.
    pause
    exit /b 1
)

:: Auto-update: pull latest from repo before launch. Non-fatal if git missing
:: or offline — we fall through to the bundled copy.
if exist "%INSTALL_DIR%\.git" (
    pushd "%INSTALL_DIR%" >nul
    git pull --ff-only origin main >>"%LOG_FILE%" 2>&1
    popd >nul
)

echo [%date% %time%] launcher starting>>"%LOG_FILE%"
echo [%date% %time%] VENV_PY=%VENV_PY%>>"%LOG_FILE%"
echo [%date% %time%] LAUNCH_PY=%LAUNCH_PY%>>"%LOG_FILE%"

:: Prefer the bundled venv (always has fastapi/uvicorn/pywinpty pre-installed
:: by setup-windows.ps1). Fall back to system python only if the venv is
:: missing — we skip pip-install-on-launch because double-click UX can't
:: survive a compile failure.
if exist "%VENV_PY%" (
    echo [launcher] using bundled venv>>"%LOG_FILE%"
    "%VENV_PY%" "%LAUNCH_PY%" >>"%LOG_FILE%" 2>&1
    exit /b %errorlevel%
)

echo [launcher] venv missing — falling back to system python>>"%LOG_FILE%"
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   Python not found. Reinstall ApplyLoop from:
    echo     https://applyloop.vercel.app/setup
    pause
    exit /b 1
)
python "%LAUNCH_PY%" >>"%LOG_FILE%" 2>&1
exit /b %errorlevel%
