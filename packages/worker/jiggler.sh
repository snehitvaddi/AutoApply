#!/bin/bash
# jiggler.sh — Prevents Mac from sleeping + jiggles the mouse every 10s.
# Uses macOS built-in caffeinate + CoreGraphics via Python (ships with macOS).
#
# Usage:
#   Start:  ./jiggler.sh
#   Stop:   ./jiggler.sh stop
#
# Singleton-guarded: a second start while one is running aborts cleanly
# instead of spawning more zombies. The stop command kills children by
# parent PID (pkill -P) which actually works, unlike the broken process-
# group kill the previous version tried (kill -- -PID requires a PGID).

PIDFILE="/tmp/jiggler.pid"
MAX_DURATION_SECONDS=86400  # 24h auto-stop safety cap

stop_jiggler() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if kill -0 "$PID" 2>/dev/null; then
            # Kill children first (caffeinate + jiggle_loop subshell),
            # then the parent. pkill -P targets children by parent PID.
            pkill -P "$PID" 2>/dev/null
            kill "$PID" 2>/dev/null
        fi
        rm -f "$PIDFILE"
    fi
    # Belt-and-suspenders: kill any strays by name that escaped the PID file
    pkill -f "jiggler.sh" 2>/dev/null
    pkill -f "caffeinate -dis" 2>/dev/null
    echo "Jiggler stopped."
}

if [ "$1" = "stop" ]; then
    stop_jiggler
    exit 0
fi

# ── Singleton guard ─────────────────────────────────────────────────────
# Abort if another jiggler is already running. This prevents the zombie
# pile-up bug where 15+ instances accumulate over time.
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Jiggler already running (PID $OLD_PID). Use '$0 stop' first."
        exit 0
    fi
    # Stale PID file — clean it up
    rm -f "$PIDFILE"
fi

# Also check for strays not tracked in the PID file (e.g. from a crash).
# CRITICAL: exclude self ($$) and parent ($PPID) from the kill list — without
# that, pkill -f "jiggler.sh" would match our own process and commit suicide
# mid-startup, which was exactly the bug that kept the script from running.
STRAYS=$(pgrep -f "jiggler.sh" | grep -v -E "^($$|$PPID)$")
if [ -n "$STRAYS" ]; then
    echo "Found stray jiggler instance(s): $(echo "$STRAYS" | tr '\n' ' '). Cleaning up..."
    for stray_pid in $STRAYS; do
        kill "$stray_pid" 2>/dev/null
    done
    pkill -f "caffeinate -dis" 2>/dev/null
    sleep 1
fi

# ── Mouse jiggle loop (no extra processes beyond caffeinate) ────────────
jiggle_loop() {
    local tick=0
    local max_ticks=$((MAX_DURATION_SECONDS / 10))  # 10s per tick
    while [ "$tick" -lt "$max_ticks" ]; do
        # CoreGraphics via python3 (ships with macOS) for reliable mouse jiggle
        python3 -c "
import Quartz, time
pos = Quartz.NSEvent.mouseLocation()
screenH = Quartz.CGDisplayPixelsHigh(Quartz.CGMainDisplayID())
cx, cy = pos.x, screenH - pos.y
Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (cx+1, cy), 0))
time.sleep(0.05)
Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (cx, cy), 0))
" 2>/dev/null
        sleep 10
        tick=$((tick + 1))
    done
    echo "Jiggler auto-stopped after 24 hours."
}

# Start caffeinate in background (blocks sleep system-wide)
caffeinate -dis &
CAFE_PID=$!

# Save our own PID so `stop` can find us
echo $$ > "$PIDFILE"

# Clean up children on exit (SIGTERM, SIGINT, normal exit)
trap "kill $CAFE_PID 2>/dev/null; rm -f $PIDFILE; exit 0" EXIT INT TERM

echo "Jiggler running (PID $$) — mouse jiggles every 10s, sleep blocked."
echo "Stop with: $0 stop"

# Run the jiggle loop in the foreground — no extra background subshell.
# The 24h auto-stop is now built into the loop's tick counter above.
jiggle_loop
