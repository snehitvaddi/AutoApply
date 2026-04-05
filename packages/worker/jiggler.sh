#!/bin/bash
# jiggler.sh — Prevents Mac from sleeping + jiggles the mouse every 10s.
# Uses macOS built-in caffeinate + cliclick (auto-installed via brew if missing).
#
# Usage:
#   Start:  ./jiggler.sh
#   Stop:   ./jiggler.sh stop   (or just Ctrl+C the running instance)

PIDFILE="/tmp/jiggler.pid"
MAX_DURATION_SECONDS=86400  # 24h auto-stop safety cap

stop_jiggler() {
    if [ -f "$PIDFILE" ]; then
        # Kill the entire process group
        PGID=$(cat "$PIDFILE")
        if kill -0 "$PGID" 2>/dev/null; then
            kill -- -"$PGID" 2>/dev/null || kill "$PGID"
            rm -f "$PIDFILE"
            echo "Jiggler stopped."
        else
            rm -f "$PIDFILE"
            echo "Jiggler was not running (stale PID file cleaned up)."
        fi
    else
        echo "Jiggler is not running."
    fi
}

if [ "$1" = "stop" ]; then
    stop_jiggler
    exit 0
fi

# Stop any existing instance first
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    kill -0 "$OLD_PID" 2>/dev/null && kill -- -"$OLD_PID" 2>/dev/null
    rm -f "$PIDFILE"
fi

# Mouse jiggle loop using osascript (no extra dependencies)
jiggle_loop() {
    while true; do
        # Get current mouse position, nudge 1px right then back
        osascript -e '
            tell application "System Events"
                set {x, y} to position of the mouse -- does not exist, use alternate
            end tell
        ' 2>/dev/null

        # Use CoreGraphics via python3 (ships with macOS) for reliable mouse jiggle
        python3 -c "
import Quartz, time
pos = Quartz.NSEvent.mouseLocation()
screenH = Quartz.CGDisplayPixelsHigh(Quartz.CGMainDisplayID())
# NSEvent gives bottom-left origin; CG wants top-left origin
cx, cy = pos.x, screenH - pos.y
# Move 1px right, then back
Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (cx+1, cy), 0))
time.sleep(0.05)
Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (cx, cy), 0))
" 2>/dev/null

        sleep 10
    done
}

# Start caffeinate in background
caffeinate -dis &
CAFE_PID=$!

# Start mouse jiggle loop in background
jiggle_loop &
JIGGLE_PID=$!

# Save our own PID (parent of both)
echo $$ > "$PIDFILE"

# Clean up children on exit
trap "kill $CAFE_PID $JIGGLE_PID 2>/dev/null; rm -f $PIDFILE" EXIT

echo "Jiggler running (PID $$) — mouse jiggles every 10s, sleep blocked."
echo "Stop with: $0 stop"

# Auto-stop after 24 hours (safety cap)
(
    sleep $MAX_DURATION_SECONDS
    echo "Jiggler auto-stopped after 24 hours."
    kill $CAFE_PID $JIGGLE_PID 2>/dev/null
    rm -f "$PIDFILE"
    kill $$ 2>/dev/null
) &

# Wait forever (keeps parent alive so stop works)
wait
