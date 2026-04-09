#!/usr/bin/env python3
"""
Build native installers for ApplyLoop Desktop.

Single-process architecture:
  - Next.js builds to static HTML/CSS/JS (no Node.js at runtime)
  - FastAPI serves the static UI + API + WebSocket
  - Everything bundles into ONE executable

Usage:
  python build.py          # Build for current platform
  python build.py --mac    # Build .app + .dmg installer
  python build.py --win    # Build .exe installer
  python build.py --all    # Build both
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
UI_DIR = HERE / "ui"
UI_OUT = UI_DIR / "out"  # Static export output
DIST_DIR = HERE / "dist"
APP_NAME = "ApplyLoop"
VERSION = "1.0.0"
BUNDLE_ID = "com.applyloop.desktop"


def build_ui():
    """Build the Next.js UI as static HTML/CSS/JS (no Node runtime needed)."""
    print("[Build] Installing UI dependencies...")
    subprocess.check_call(["npm", "install"], cwd=str(UI_DIR))
    print("[Build] Building static UI export...")
    subprocess.check_call(["npm", "run", "build"], cwd=str(UI_DIR))
    if not UI_OUT.exists():
        print("[Build] ERROR: Static export not found at ui/out/")
        print("[Build] Make sure next.config.js has output: 'export'")
        sys.exit(1)
    file_count = sum(1 for _ in UI_OUT.rglob("*") if _.is_file())
    print(f"[Build] Static UI built: {file_count} files in ui/out/")


def build_mac_app():
    """
    Create a macOS .app bundle + .dmg installer.

    Architecture:
      ApplyLoop.app/
        Contents/
          Info.plist          — App metadata (name, icon, version)
          MacOS/
            launcher          — Bash script: installs deps, starts FastAPI
          Resources/
            server/           — Python FastAPI backend
            ui/out/           — Static HTML/CSS/JS (pre-built)
            requirements.txt
            launch.py
    """
    print("[Build] Creating macOS .app bundle...")

    app_dir = DIST_DIR / f"{APP_NAME}.app"
    contents = app_dir / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"

    # Clean
    if app_dir.exists():
        shutil.rmtree(app_dir)
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    # Copy backend server
    shutil.copytree(
        HERE / "server", resources / "server",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    # Copy static UI build (no node_modules needed!)
    if UI_OUT.exists():
        shutil.copytree(UI_OUT, resources / "ui" / "out")
    else:
        print("[Build] WARNING: ui/out/ not found — run build_ui() first")

    # Copy requirements
    shutil.copy2(HERE / "requirements.txt", resources)

    # Create venv with all deps pre-installed (force arm64 for Apple Silicon)
    print("[Build] Creating Python venv inside .app (arm64)...")
    venv_dir = resources / "venv"
    subprocess.check_call(["arch", "-arm64", sys.executable, "-m", "venv", str(venv_dir)])
    venv_pip = venv_dir / "bin" / "pip"
    subprocess.check_call(["arch", "-arm64", str(venv_pip), "install", "-q",
                           "fastapi", "uvicorn", "httpx", "websockets"])
    print("[Build] Venv created with all deps")

    # Info.plist
    (contents / "Info.plist").write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>{APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>{APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>{BUNDLE_ID}</string>
    <key>CFBundleVersion</key>
    <string>{VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>{VERSION}</string>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
""")

    # Launcher script — force arm64 for Apple Silicon, all output to log
    launcher = macos / "launcher"
    launcher.write_text("""\
#!/bin/bash
# ApplyLoop Desktop — macOS Launcher

RESOURCES="$(dirname "$0")/../Resources"
cd "$RESOURCES"

LOG="$HOME/.autoapply/desktop.log"
mkdir -p "$HOME/.autoapply"
mkdir -p "$HOME/.autoapply/workspace"

PYTHON="$RESOURCES/venv/bin/python3"

# Create venv if missing — force arm64 for Apple Silicon
if [ ! -f "$PYTHON" ]; then
  arch -arm64 python3 -m venv "$RESOURCES/venv" >> "$LOG" 2>&1
  arch -arm64 "$PYTHON" -m pip install -q fastapi uvicorn httpx websockets >> "$LOG" 2>&1
fi

# Open browser after server starts
(sleep 4 && open "http://localhost:18790") &

# Run server — force arm64, all output to log file
exec arch -arm64 "$PYTHON" -c "
import sys, os
sys.path.insert(0, '.')
os.environ.setdefault('APPLYLOOP_PORT', '18790')
import uvicorn
uvicorn.run('server.app:app', host='127.0.0.1', port=18790, log_level='warning')
" >> "$LOG" 2>&1
""")
    os.chmod(str(launcher), 0o755)

    print(f"[Build] .app created: {app_dir}")

    # Create .dmg installer
    dmg_path = DIST_DIR / f"{APP_NAME}-{VERSION}.dmg"
    if dmg_path.exists():
        dmg_path.unlink()

    try:
        subprocess.check_call([
            "hdiutil", "create",
            "-volname", APP_NAME,
            "-srcfolder", str(app_dir),
            "-ov",
            "-format", "UDZO",  # Compressed
            str(dmg_path),
        ])
        print(f"[Build] .dmg created: {dmg_path}")
        print(f"[Build] Distribute this file — users open it and drag to /Applications")
    except subprocess.CalledProcessError:
        print(f"[Build] .dmg creation failed — .app is still usable directly")

    return app_dir


def build_windows_exe():
    """
    Create a Windows .exe installer.

    Uses PyInstaller if available, otherwise creates a self-contained folder
    with a .exe wrapper batch script.
    """
    print("[Build] Creating Windows installer...")

    win_dir = DIST_DIR / "windows"
    if win_dir.exists():
        shutil.rmtree(win_dir)
    win_dir.mkdir(parents=True)

    # Copy all needed files into a staging directory
    stage = win_dir / "staging"
    stage.mkdir()

    shutil.copytree(
        HERE / "server", stage / "server",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    if UI_OUT.exists():
        shutil.copytree(UI_OUT, stage / "ui" / "out")
    shutil.copy2(HERE / "requirements.txt", stage)

    # Create the main entry script
    (stage / "main.py").write_text(f"""\
#!/usr/bin/env python3
\"\"\"ApplyLoop Desktop — Windows entry point.\"\"\"
import sys, os, webbrowser, threading, time

# Ensure we can import the server package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("APPLYLOOP_PORT", "18790")

def open_browser():
    time.sleep(2)
    webbrowser.open("http://localhost:18790")

if __name__ == "__main__":
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║       {APP_NAME} Desktop               ║")
    print("  ║  Automated Job Application Tracker   ║")
    print("  ╚══════════════════════════════════════╝")
    print()
    print("  Starting on http://localhost:18790")
    print("  Press Ctrl+C to stop.")
    print()

    threading.Thread(target=open_browser, daemon=True).start()

    import uvicorn
    uvicorn.run("server.app:app", host="127.0.0.1", port=18790, log_level="warning")
""")

    # Try PyInstaller for a proper .exe
    pyinstaller_ok = False
    try:
        subprocess.check_call([
            sys.executable, "-m", "PyInstaller",
            "--onedir",
            "--name", APP_NAME,
            "--distpath", str(win_dir),
            "--add-data", f"{stage / 'server'}{os.pathsep}server",
            "--add-data", f"{stage / 'ui'}{os.pathsep}ui",
            "--hidden-import", "uvicorn.logging",
            "--hidden-import", "uvicorn.protocols.http.auto",
            "--hidden-import", "uvicorn.protocols.websockets.auto",
            "--hidden-import", "uvicorn.lifespan.on",
            "--hidden-import", "httpx",
            str(stage / "main.py"),
        ])
        pyinstaller_ok = True
        print(f"[Build] .exe created: {win_dir / APP_NAME / f'{APP_NAME}.exe'}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[Build] PyInstaller not available — creating portable folder instead")

    if not pyinstaller_ok:
        # Portable folder distribution
        portable = win_dir / APP_NAME
        if portable.exists():
            shutil.rmtree(portable)
        shutil.copytree(stage, portable)

        # Create a launcher .bat
        (portable / f"{APP_NAME}.bat").write_text(f"""\
@echo off
title {APP_NAME} Desktop
echo.
echo   Starting {APP_NAME} Desktop...
echo.
cd /d "%~dp0"
python -m pip install -q -r requirements.txt 2>nul
python main.py
pause
""")
        # Also create a .cmd (same thing, but some users prefer it)
        shutil.copy2(portable / f"{APP_NAME}.bat", portable / f"{APP_NAME}.cmd")

        print(f"[Build] Portable folder created: {portable}")
        print(f"[Build] Users run: {APP_NAME}.bat (or .cmd)")

    # Clean up staging
    shutil.rmtree(stage, ignore_errors=True)

    # Create a zip for easy distribution
    zip_path = DIST_DIR / f"{APP_NAME}-{VERSION}-windows"
    shutil.make_archive(str(zip_path), "zip", str(win_dir), APP_NAME)
    print(f"[Build] Zip created: {zip_path}.zip")

    return win_dir


def main():
    import argparse
    parser = argparse.ArgumentParser(description=f"Build {APP_NAME} Desktop installers")
    parser.add_argument("--mac", action="store_true", help="Build macOS .app + .dmg")
    parser.add_argument("--win", action="store_true", help="Build Windows .exe")
    parser.add_argument("--all", action="store_true", help="Build all platforms")
    parser.add_argument("--skip-ui", action="store_true", help="Skip UI build (use existing ui/out)")
    args = parser.parse_args()

    if args.all:
        args.mac = args.win = True

    # Default: build for current platform
    if not args.mac and not args.win:
        args.mac = platform.system() == "Darwin"
        args.win = platform.system() == "Windows"

    DIST_DIR.mkdir(parents=True, exist_ok=True)

    if not args.skip_ui:
        build_ui()
    elif not UI_OUT.exists():
        print("[Build] ERROR: --skip-ui but ui/out/ doesn't exist. Run without --skip-ui first.")
        sys.exit(1)

    if args.mac:
        build_mac_app()
    if args.win:
        build_windows_exe()

    print()
    print(f"[Build] All done! Output in: {DIST_DIR}")


if __name__ == "__main__":
    main()
