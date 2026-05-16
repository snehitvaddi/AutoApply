#!/usr/bin/env python3
"""
Build native installers for ApplyLoop Desktop.

Single-process architecture:
  - Next.js builds to static HTML/CSS/JS (no Node.js at runtime)
  - FastAPI serves the static UI + API + WebSocket
  - Everything bundles into ONE executable

DEPRECATED as of v1.0.8 — the primary install path is now the curl
script at `install.sh` in the repo root, which builds the .app bundle
on the user's machine instead of shipping it pre-built. The local
approach sidesteps macOS Gatekeeper entirely (locally-built bundles
have no quarantine bit) and removes the need for codesigning or
notarization. This file is kept around for power users who want a
fully self-contained .dmg without an internet-dependent install, but
new releases no longer cut .dmg artifacts. Gatekeeper-related issues
should be reported against the install.sh path instead.

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
VERSION = "1.0.7"
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

    # Copy requirements and launcher
    shutil.copy2(HERE / "requirements.txt", resources)
    shutil.copy2(HERE / "launch.py", resources)

    # Copy app icon
    icon_src = HERE / "AppIcon.icns"
    if icon_src.exists():
        shutil.copy2(icon_src, resources / "AppIcon.icns")

    # Create venv with all deps pre-installed. Previously this was hardcoded
    # to `arch -arm64`, which crashed on Intel Macs ("Bad CPU type in
    # executable"). Detect the host arch and use it instead.
    host_arch = platform.machine()  # "arm64" on Apple Silicon, "x86_64" on Intel
    arch_flag = f"-{host_arch}"
    print(f"[Build] Creating Python venv inside .app ({host_arch})...")
    venv_dir = resources / "venv"
    try:
        subprocess.check_call(
            ["arch", arch_flag, sys.executable, "-m", "venv", str(venv_dir)]
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # `arch` unavailable (non-macOS) or unsupported flag: fall back to
        # the running interpreter directly.
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
    venv_pip = venv_dir / "bin" / "pip"
    # NOTE: keep this list in sync with packages/desktop/requirements.txt
    # Missing python-multipart caused v1.0.4 to crash on launch because
    # FastAPI imports the UploadFile/Form resume-upload route at module
    # load time, which requires python-multipart. Learned the hard way.
    _pip_pkgs = ["fastapi", "uvicorn", "httpx", "websockets",
                 "pywebview", "python-multipart"]
    pip_cmd = ["arch", arch_flag, str(venv_pip), "install", "-q"] + _pip_pkgs
    try:
        subprocess.check_call(pip_cmd)
    except (subprocess.CalledProcessError, FileNotFoundError):
        subprocess.check_call([str(venv_pip), "install", "-q"] + _pip_pkgs)
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
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
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

    # Launcher script — executes the bundled venv's python directly so we
    # never touch system python3. Before v1.0.6 this ran `arch -arm64 python3
    # launch.py` against Xcode's /usr/bin/python3, which has no fastapi, so
    # launch.py::check_deps() would try to pip install from requirements.txt,
    # which pulls pywebview → pyobjc-core → needs a C compiler the user
    # doesn't have → the whole app dies on first launch. The venv we ship
    # inside the .app bundle already has every dep baked in, so just use it.
    launcher = macos / "launcher"
    launcher.write_text("""\
#!/bin/bash
# ApplyLoop Desktop — macOS Launcher (uses bundled venv python)

RESOURCES="$(dirname "$0")/../Resources"
cd "$RESOURCES"

LOG="$HOME/.autoapply/desktop.log"
mkdir -p "$HOME/.autoapply"
mkdir -p "$HOME/.autoapply/workspace"

VENV_PY="$RESOURCES/venv/bin/python3"

# Record what we're doing so users can paste the log if something breaks.
{
  echo "[launcher] $(date '+%Y-%m-%d %H:%M:%S') starting"
  echo "[launcher] RESOURCES=$RESOURCES"
  echo "[launcher] VENV_PY=$VENV_PY"
} >> "$LOG" 2>&1

# Prefer the bundled venv. Fall back to system python3 only if the venv
# is somehow missing (broken install, user copied the launcher out of the
# bundle, etc.) — in that fallback we STILL skip pip install at launch
# because downloading fresh wheels from a double-click is too fragile.
if [ -x "$VENV_PY" ]; then
  echo "[launcher] using bundled venv" >> "$LOG" 2>&1
  exec "$VENV_PY" launch.py >> "$LOG" 2>&1
else
  echo "[launcher] venv missing — falling back to system python3" >> "$LOG" 2>&1
  exec /usr/bin/env python3 launch.py >> "$LOG" 2>&1
fi
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
    # The embedded main.py is what PyInstaller wraps into ApplyLoop.exe.
    # Two encoding-related landmines we must avoid:
    # 1. Path.write_text defaults to cp1252 on Windows. We pass
    #    encoding="utf-8" so the file write doesn't crash on any non-ASCII.
    # 2. AT RUNTIME, when the frozen .exe runs with redirected stdout
    #    (CI, services, no console), Python defaults stdout encoding to
    #    cp1252 too, so `print(non-ASCII)` raises UnicodeEncodeError. We
    #    reconfigure stdout/stderr to utf-8 before the first print, AND
    #    keep the banner pure-ASCII so it works even on Python builds
    #    that don't expose .reconfigure().
    (stage / "main.py").write_text(f"""\
#!/usr/bin/env python3
\"\"\"ApplyLoop Desktop -- Windows entry point.\"\"\"
import sys, os, webbrowser, threading, time, traceback, datetime

# Force UTF-8 on stdout/stderr if the runtime supports it (3.7+).
# Without this, a frozen .exe with redirected stdout falls back to
# cp1252 and any non-ASCII print() crashes the whole process.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# Crash log: always tee fatal errors to %USERPROFILE%\\.autoapply\\applyloop-crash.log
# so a user who double-clicks the shortcut and sees a console flash-and-
# vanish can at least find out WHY when they ask us for help. Without this,
# a startup crash (port collision, BOM in token, missing dep) leaves no
# trace because the console window dies before the user can read anything.
_CRASH_LOG = os.path.join(
    os.environ.get("USERPROFILE") or os.path.expanduser("~"),
    ".autoapply", "applyloop-crash.log",
)
os.makedirs(os.path.dirname(_CRASH_LOG), exist_ok=True)

def _write_crash(msg: str) -> None:
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            ts = datetime.datetime.now().isoformat(timespec="seconds")
            f.write(f"\\n[{{ts}}] {{msg}}\\n")
    except Exception:
        pass

# Ensure we can import the server package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("APPLYLOOP_PORT", "18790")
PORT = int(os.environ["APPLYLOOP_PORT"])

def _wait_for_server(port, timeout_s=30):
    \"\"\"Block until uvicorn has bound to localhost:port, or timeout.
    The webview window/browser tab must NOT open until the server is
    serving — otherwise the user sees "site can't be reached" while
    uvicorn is still booting.\"\"\"
    import socket as _socket
    end = time.time() + timeout_s
    while time.time() < end:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(0.2)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            pass
        time.sleep(0.2)
    return False

def open_browser():
    if _wait_for_server(PORT):
        # Use 127.0.0.1 explicitly. On Windows 10/11, `localhost`
        # resolves to ::1 (IPv6) before 127.0.0.1 (IPv4). uvicorn
        # binds IPv4 only — so the user's browser tab opened on
        # `localhost` would try ::1 first, get connection-refused,
        # and either fall back to IPv4 (slow) or fail outright
        # depending on the browser. 127.0.0.1 sidesteps the dual-
        # stack guess.
        webbrowser.open(f"http://127.0.0.1:{{PORT}}")

def _hold_console_on_error() -> None:
    \"\"\"If the .exe was launched by a double-click (no parent console
    inherited from the caller), the console window we're running in
    dies the instant Python exits. Without a pause, the user sees a
    flash and has no way to read the traceback. The PYTHONUNBUFFERED
    + console=True PyInstaller build means we have a real console;
    we just need to keep it alive long enough to be read.\"\"\"
    if sys.platform == "win32":
        try:
            input("\\n[applyloop] Press Enter to close this window (error details above are also at %USERPROFILE%\\\\.autoapply\\\\applyloop-crash.log)... ")
        except Exception:
            time.sleep(30)

def _probe_localhost(port: int, timeout_s: float = 0.5) -> bool:
    import socket as _socket
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s.settimeout(timeout_s)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except OSError:
        return False

if __name__ == "__main__":
    print()
    print("  +--------------------------------------+")
    print("  |       {APP_NAME} Desktop               |")
    print("  |  Automated Job Application Tracker   |")
    print("  +--------------------------------------+")
    print()
    print(f"  Starting on http://127.0.0.1:{{PORT}}")
    print("  Press Ctrl+C to stop.")
    print()

    # Run uvicorn in a background thread so the main thread can drive a
    # native window (pywebview / Edge WebView2). Without this, uvicorn.run()
    # blocks forever and we never reach the GUI start. The thread is
    # non-daemon so the process stays alive while uvicorn is serving even
    # if the GUI fails to start (the browser fallback below joins it).
    def _run_server():
        try:
            # Force PyInstaller to bundle these -- uvicorn loads via string
            # import "server.app:app" which the static analyzer can't see.
            import fastapi  # noqa: F401
            import server.app  # noqa: F401
            import uvicorn as _uvi
            _uvi.run("server.app:app", host="127.0.0.1", port=PORT, log_level="warning")
        except Exception as _e:
            _tb = traceback.format_exc()
            print("\\n[applyloop] FATAL: uvicorn thread crashed:")
            print(_tb)
            _write_crash(f"uvicorn thread: {{type(_e).__name__}}: {{_e}}\\n{{_tb}}")
    _server_thread = threading.Thread(target=_run_server, name="applyloop-server", daemon=False)
    _server_thread.start()

    # Wait for the actual bind so neither the webview nor the browser
    # fallback opens before the server is ready. 120s — not 30s.
    # The FastAPI lifespan startup probes OpenClaw gateway (each probe
    # has a 5s timeout, and one of them retries), so on first boot
    # with a stale gateway state lifespan startup legitimately takes
    # 20-40 seconds. The old 30s probe was firing false-positives:
    # printing "FATAL: uvicorn never bound", exiting the main thread,
    # and stranding the non-daemon server thread serving requests with
    # no native window driver. User sees console-only "broken" UX
    # despite the server being healthy. 120s comfortably covers worst
    # case + leaves margin for slow disks / cold network.
    if not _wait_for_server(PORT, timeout_s=120):
        print("\\n[applyloop] FATAL: uvicorn never bound to localhost.")
        print("[applyloop] Scroll up for the actual error (look for 'Application")
        print("[applyloop]   startup failed' or a Python traceback).")
        _write_crash("uvicorn never bound to localhost after 120s -- see console above")
        _hold_console_on_error()
        sys.exit(1)

    # ── Try pywebview (native Windows window via Edge WebView2). On
    # Windows 11 and Win10/1809+ with current Edge, WebView2 is
    # preinstalled. If pywebview can't start (WebView2 runtime missing,
    # COM init failure, etc.), fall back to the default browser.
    _url = f"http://127.0.0.1:{{PORT}}"  # IPv4 explicit; avoids localhost→::1 trap on Windows
    print("[applyloop] Attempting native window via pywebview/WebView2...")
    try:
        import webview  # pywebview
        print(f"[applyloop] pywebview imported (version={{getattr(webview, '__version__', 'unknown')}})")

        _icon_path = None
        for _cand_dir in (getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__))):
            if not _cand_dir:
                continue
            _c = os.path.join(_cand_dir, "icon.ico")
            if os.path.isfile(_c):
                _icon_path = _c
                break

        _kwargs = {{
            "title": "ApplyLoop",
            "url": _url,
            "width": 1400,
            "height": 900,
            "min_size": (800, 600),
            "text_select": True,
        }}
        if _icon_path:
            try:
                import inspect
                if "icon" in inspect.signature(webview.create_window).parameters:
                    _kwargs["icon"] = _icon_path
            except Exception:
                pass

        _window = webview.create_window(**_kwargs)

        def _on_closed():
            # Closing the native window means the user wants the app
            # gone. taskkill /T /F walks the process tree so worker.py
            # + Claude PTY + jiggler + caffeinate analogs all die.
            try:
                import subprocess as _subp
                _subp.run(
                    ["taskkill", "/F", "/T", "/PID", str(os.getpid())],
                    capture_output=True, timeout=3,
                )
            except Exception:
                pass
            os._exit(0)

        _window.events.closed += _on_closed
        # webview.start() blocks until the window closes. pywebview picks
        # the Edge WebView2 GUI backend on Windows automatically.
        print("[applyloop] Starting GUI loop (window should open now)")
        webview.start(debug=False, private_mode=False)
    except Exception as _gui_err:
        # Loud + persisted so we can actually diagnose. The previous bug
        # report ("just opened Chrome instead of native window") only said
        # the fallback fired — not WHY. _write_crash + console print
        # together let us see the cause either way.
        _gui_tb = traceback.format_exc()
        print(f"[applyloop] Native window unavailable: {{_gui_err}}")
        print(f"[applyloop] Full traceback:\\n{{_gui_tb}}")
        print(f"[applyloop] Opening browser fallback instead.")
        _write_crash(f"pywebview unavailable, fell back to browser: {{_gui_err}}\\n{{_gui_tb}}")
        try:
            webbrowser.open(_url)
        except Exception:
            pass
        # No GUI to block on -- wait on the server thread instead, so
        # closing the console (or Ctrl+C) is what stops the app.
        try:
            _server_thread.join()
        except KeyboardInterrupt:
            print("\\n[applyloop] Stopped by user.")
            sys.exit(0)
""", encoding="utf-8")

    # Try PyInstaller for a proper .exe
    pyinstaller_ok = False
    # Embed the blue "A" icon into the .exe so File Explorer, Alt-Tab, the
    # taskbar, and the Start Menu shortcut all show the brand mark instead
    # of PyInstaller's default Python placeholder. icon.ico is committed
    # next to build.py and contains 16/32/48/64/128/256 sizes so each
    # Windows surface picks the best fit without scaling artifacts.
    icon_path = HERE / "icon.ico"
    icon_args = ["--icon", str(icon_path)] if icon_path.exists() else []
    if not icon_path.exists():
        print(f"[Build] WARN: {icon_path.name} not found — .exe will use the default PyInstaller icon")
    try:
        subprocess.check_call([
            sys.executable, "-m", "PyInstaller",
            "--onedir",
            "--name", APP_NAME,
            "--distpath", str(win_dir),
            *icon_args,
            "--add-data", f"{stage / 'server'}{os.pathsep}server",
            "--add-data", f"{stage / 'ui'}{os.pathsep}ui",
            # Ship icon.ico inside the bundle so pywebview can hand it to
            # WebView2 as the window title-bar icon. Resolved at runtime
            # via sys._MEIPASS.
            *(["--add-data", f"{icon_path}{os.pathsep}."] if icon_path.exists() else []),
            # --collect-submodules grabs every submodule under the named
            # package even if the static analyzer can't see the import.
            # Without these, PyInstaller emits a stub that fails at runtime
            # with ModuleNotFoundError for fastapi/starlette/etc.
            "--collect-submodules", "server",
            "--collect-submodules", "fastapi",
            "--collect-submodules", "starlette",
            "--collect-submodules", "uvicorn",
            "--collect-submodules", "pydantic",
            # pywebview: --collect-all picks up the data files (HTML/CSS
            # the JS bridge needs) AND every platform backend submodule.
            # Without --collect-all the EdgeChromium loader can't find
            # its bundled scripts at runtime and webview.start() raises
            # "No module named 'webview.platforms.edgechromium'".
            "--collect-all", "webview",
            # Transitive deps PyInstaller frequently misses for the Windows
            # WebView2 backend. Each one of these has been the *single*
            # missing piece in past pywebview-on-Windows bug reports:
            #   - proxy_tools  → @serve_static decorator pywebview uses
            #   - bottle       → embedded HTTP shim for html=... windows
            #   - clr_loader / pythonnet → CLR bridge the older mshtml
            #     fallback needs (kept for graceful degradation on
            #     machines without WebView2 runtime)
            #   - typing_extensions → backport pywebview imports for 3.10
            "--collect-all", "proxy_tools",
            "--collect-all", "bottle",
            "--hidden-import", "clr_loader",
            "--hidden-import", "pythonnet",
            "--hidden-import", "typing_extensions",
            # Force the EdgeChromium backend module into the bundle
            # explicitly. --collect-all webview SHOULD grab this, but
            # at least one user-reported PyInstaller version dropped it
            # silently. Belt-and-suspenders.
            "--hidden-import", "webview.platforms.edgechromium",
            "--hidden-import", "webview.platforms.winforms",
            "--hidden-import", "webview.platforms.mshtml",
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
