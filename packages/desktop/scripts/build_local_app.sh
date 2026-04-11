#!/usr/bin/env bash
# Generate a thin /Applications/ApplyLoop.app bundle that launches the
# installed venv + launch.py at $APPLYLOOP_HOME. The bundle contains no
# code — just an Info.plist, a bash launcher, and the icon. Because it's
# created locally by this script, macOS does NOT attach the quarantine
# bit, so double-click works with zero Gatekeeper interaction.
set -euo pipefail

APPLYLOOP_HOME="${APPLYLOOP_HOME:-$HOME/.applyloop}"
APP_DIR="${APPLYLOOP_APP:-/Applications/ApplyLoop.app}"

if [[ -f "$APPLYLOOP_HOME/packages/desktop/VERSION" ]]; then
  VERSION="$(tr -d '[:space:]' < "$APPLYLOOP_HOME/packages/desktop/VERSION")"
else
  VERSION="1.0.8"
fi

echo "[build_local_app] Generating $APP_DIR (version $VERSION) pointing at $APPLYLOOP_HOME"

# Wipe any prior bundle to guarantee a clean install
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

# Info.plist — fields copied verbatim from packages/desktop/build.py::build_mac_app
cat > "$APP_DIR/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>ApplyLoop</string>
    <key>CFBundleDisplayName</key>
    <string>ApplyLoop</string>
    <key>CFBundleIdentifier</key>
    <string>com.applyloop.desktop</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
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
EOF

# MacOS/launcher — tiny bash shim that execs the installed venv python.
# Kept in single-quoted heredoc so $HOME / $APPLYLOOP_HOME are resolved
# at RUN time, not generate time.
cat > "$APP_DIR/Contents/MacOS/launcher" <<'EOF'
#!/bin/bash
# ApplyLoop launcher — execs the venv python at $APPLYLOOP_HOME.
APPLYLOOP_HOME="${APPLYLOOP_HOME:-$HOME/.applyloop}"
LOG="$HOME/.autoapply/desktop.log"
mkdir -p "$HOME/.autoapply" "$HOME/.autoapply/workspace"

# CRITICAL: when an .app is launched from Finder/Dock, macOS gives the
# process a bare PATH (/usr/bin:/bin:/usr/sbin:/sbin) — NOT the PATH
# from the user's interactive shell. That means /opt/homebrew/bin and
# /usr/local/bin are missing, so the preflight check's
# `shutil.which("npm")` / `which("openclaw")` returns None even though
# both binaries exist on disk. Source brew's shellenv to fix it before
# the python process inherits our environment.
if [[ -x /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ -x /usr/local/bin/brew ]]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi
# Also include the npm global bin (where openclaw lands) and ~/.local/bin
# for the applyloop CLI shim.
if command -v npm >/dev/null 2>&1; then
  NPM_PREFIX="$(npm config get prefix 2>/dev/null || true)"
  if [[ -n "$NPM_PREFIX" && -d "$NPM_PREFIX/bin" ]]; then
    PATH="$NPM_PREFIX/bin:$PATH"
  fi
fi
PATH="$HOME/.local/bin:$PATH"
export PATH

{
  echo "[launcher] $(date '+%Y-%m-%d %H:%M:%S') starting"
  echo "[launcher] APPLYLOOP_HOME=$APPLYLOOP_HOME"
  echo "[launcher] PATH=$PATH"
} >> "$LOG" 2>&1

if [[ ! -x "$APPLYLOOP_HOME/venv/bin/python3" ]]; then
  osascript -e 'display alert "ApplyLoop not installed" message "Run the curl installer first:\n\ncurl -fsSL https://raw.githubusercontent.com/snehitvaddi/AutoApply/main/install.sh | bash"' >/dev/null 2>&1 || true
  echo "[launcher] venv missing at $APPLYLOOP_HOME/venv/bin/python3 — aborting" >> "$LOG"
  exit 1
fi

exec "$APPLYLOOP_HOME/venv/bin/python3" "$APPLYLOOP_HOME/packages/desktop/launch.py" >> "$LOG" 2>&1
EOF
chmod +x "$APP_DIR/Contents/MacOS/launcher"

# Icon (optional — falls back to generic Finder icon if missing)
if [[ -f "$APPLYLOOP_HOME/packages/desktop/AppIcon.icns" ]]; then
  cp "$APPLYLOOP_HOME/packages/desktop/AppIcon.icns" "$APP_DIR/Contents/Resources/AppIcon.icns"
  echo "[build_local_app] Copied AppIcon.icns"
else
  echo "[build_local_app] WARNING: AppIcon.icns not found at $APPLYLOOP_HOME/packages/desktop/AppIcon.icns"
fi

# Tell Launch Services about the new bundle so Spotlight + Dock pick it up now
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [[ -x "$LSREGISTER" ]]; then
  "$LSREGISTER" -f "$APP_DIR" >/dev/null 2>&1 || true
fi

echo "[build_local_app] Done. Launch with: open \"$APP_DIR\""
