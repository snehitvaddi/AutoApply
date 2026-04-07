#!/bin/bash
# ApplyLoop — One-click launcher for Mac
# Double-click in Finder to start. Runs Claude Code with full permissions.

INSTALL_DIR="$HOME/ApplyLoop"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║     ApplyLoop — Starting...              ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# Check if setup is done
if [ ! -f "$INSTALL_DIR/AGENTS.md" ]; then
    echo "  Setup not complete. Run the setup script first:"
    echo "  applyloop.vercel.app/setup-complete"
    echo ""
    read -p "  Press Enter to exit..."
    exit 1
fi

# Pull latest updates from repo
echo "  Checking for updates..."
if [ -d "$INSTALL_DIR/repo/.git" ]; then
    cd "$INSTALL_DIR/repo"
    git pull origin main >/dev/null 2>&1
    cp -r "$INSTALL_DIR/repo/"* "$INSTALL_DIR/" 2>/dev/null
    echo "  ✓ Updates applied."
elif [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR"
    git pull origin main >/dev/null 2>&1
    echo "  ✓ Updates applied."
else
    echo "  No git repo found — skipping update check."
fi

echo ""
echo "  Starting ApplyLoop with Claude Code..."
echo "  (Close this window to stop)"
echo ""

cd "$INSTALL_DIR"
claude --dangerously-skip-permissions --cd "$INSTALL_DIR" "Read AGENTS.md. You are ApplyLoop. Start the jiggler, then begin the scout→filter→apply loop using openclaw browser commands. Do NOT use web search. Do NOT run worker.py."

echo ""
echo "  ApplyLoop stopped."
read -p "  Press Enter to exit..."
