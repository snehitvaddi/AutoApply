#!/bin/bash
# ApplyLoop — Creates a proper macOS .app bundle on Desktop
# Called by setup-mac.sh after installation is complete.
# The .app shows up in Finder, Dock, Launchpad with a proper icon.

INSTALL_DIR="${1:-$HOME/ApplyLoop}"
APP_NAME="ApplyLoop"
APP_PATH="$HOME/Desktop/$APP_NAME.app"

echo "Creating $APP_NAME.app on Desktop..."

# Create .app bundle structure
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# Write Info.plist
cat > "$APP_PATH/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>ApplyLoop</string>
    <key>CFBundleDisplayName</key>
    <string>ApplyLoop</string>
    <key>CFBundleIdentifier</key>
    <string>com.applyloop.agent</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleExecutable</key>
    <string>launch</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

# Write the launcher script
cat > "$APP_PATH/Contents/MacOS/launch" <<'LAUNCHER'
#!/bin/bash
# ApplyLoop — Autonomous Job Application Bot
# This runs when you double-click the app icon.

INSTALL_DIR="$HOME/ApplyLoop"
LOG="$INSTALL_DIR/applyloop.log"

# Open Terminal with the ApplyLoop session
osascript -e "
tell application \"Terminal\"
    activate
    set newTab to do script \"
        echo ''
        echo '  ╔══════════════════════════════════════════╗'
        echo '  ║     ApplyLoop — Starting...              ║'
        echo '  ╚══════════════════════════════════════════╝'
        echo ''

        INSTALL_DIR=\\\"$HOME/ApplyLoop\\\"

        # Pull latest updates
        echo '  Checking for updates...'
        if [ -d \\\"\\$INSTALL_DIR/repo/.git\\\" ]; then
            cd \\\"\\$INSTALL_DIR/repo\\\"
            git pull origin main >/dev/null 2>&1
            cp -r \\\"\\$INSTALL_DIR/repo/\\\"* \\\"\\$INSTALL_DIR/\\\" 2>/dev/null
            echo '  ✓ Updates applied.'
        elif [ -d \\\"\\$INSTALL_DIR/.git\\\" ]; then
            cd \\\"\\$INSTALL_DIR\\\"
            git pull origin main >/dev/null 2>&1
            echo '  ✓ Updates applied.'
        fi

        echo ''
        echo '  Starting ApplyLoop with Claude Code...'
        echo '  (Close this window to stop)'
        echo ''

        cd \\\"\\$INSTALL_DIR\\\"
        claude --dangerously-skip-permissions --cd \\\"\\$INSTALL_DIR\\\" \\\"Read AGENTS.md. You are ApplyLoop. Start the jiggler, then begin the scout→filter→apply loop using openclaw browser commands. Do NOT use web search. Do NOT run worker.py.\\\"

        echo ''
        echo '  ApplyLoop stopped.'
    \"
end tell
"
LAUNCHER

chmod +x "$APP_PATH/Contents/MacOS/launch"

# Create a simple icon using sips (macOS built-in)
# Generate a blue circle with "AL" text as app icon
python3 -c "
import subprocess, os, tempfile
# Create a simple 512x512 icon using macOS built-in tools
icon_dir = '$APP_PATH/Contents/Resources'
# Use a system icon as placeholder
src = '/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/ToolbarCustomizeIcon.icns'
dst = os.path.join(icon_dir, 'AppIcon.icns')
if os.path.exists(src):
    subprocess.run(['cp', src, dst], capture_output=True)
    print('Icon set')
else:
    print('No icon available — using default')
" 2>/dev/null

echo "✓ $APP_NAME.app created on Desktop"
echo "  Double-click it in Finder to start ApplyLoop."
echo "  You can also drag it to your Dock for quick access."
